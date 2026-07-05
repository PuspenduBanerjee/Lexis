"""Live MCP server: turn a resolved model's metrics into callable, query-executing
MCP tools (not just the static schema `transpilers/mcp.py` emits).

Callers (the CLI's `mcp-serve` command, the API's mounted HTTP endpoint) supply an
`ExecuteMetric` closure that knows how to actually run a metric query against
whichever connection they've opened - this module only knows about the MCP protocol
and the tool schema, never about DuckDB/Snowflake/FastAPI/SQLAlchemy, so it works the
same from a local stdio process or a per-request HTTP handler.
"""

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import Server

from semantica.resolved_model import ResolvedModel
from semantica.transpilers.mcp import build_metric_tool_specs
from semantica.transpilers.sql.base import SqlDialectEmitter

# A metric result has no natural row limit of its own (it's an aggregate query, not a
# table scan) - this only guards against a pathological `group_by` fanning out to an
# enormous number of groups.
MAX_RESULT_ROWS = 1000


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def run_metric_query(
    con: Any,
    emitter: SqlDialectEmitter,
    model: ResolvedModel,
    metric: str,
    group_by: list[str] | None,
) -> dict:
    """Driver-agnostic metric execution - same shape as
    `semantica_api.query_runtime.run_metric_query`, duplicated here (rather than
    imported) so this core module stays free of the `semantica_api` (FastAPI/
    SQLAlchemy) dependency chain; both copies are small enough that the duplication
    is cheaper than relocating that module."""
    sql = emitter.emit_metric_query(model, metric, group_by=group_by)
    cursor = con.cursor()
    cursor.execute(sql)
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchmany(MAX_RESULT_ROWS)
    return {
        "columns": columns,
        "rows": [[_json_safe(v) for v in r] for r in rows],
        "row_count": len(rows),
        "sql": sql,
    }


ExecuteMetric = Callable[[str, list[str] | None], dict]


def build_server(model: ResolvedModel, execute: ExecuteMetric, name: str | None = None) -> Server:
    """Build an MCP `Server` with one `query_<metric>` tool per OSI metric, dispatching
    tool calls to `execute(metric_name, group_by)`."""
    tools = [types.Tool(**spec) for spec in build_metric_tool_specs(model)]
    server: Server = Server(name or model.semantic_model.name)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> dict:
        if not name.startswith("query_"):
            raise ValueError(f"unknown tool {name!r}")
        metric = name.removeprefix("query_")
        if metric not in model.metrics:
            raise ValueError(f"unknown metric {metric!r}")
        # `execute` runs a blocking DB-API call (DuckDB/Snowflake) - offload it so it
        # doesn't stall the event loop driving the MCP session (matters most for the
        # HTTP transport, which - unlike a normal FastAPI route - isn't already
        # running inside FastAPI's own sync-endpoint threadpool).
        return await anyio.to_thread.run_sync(execute, metric, arguments.get("group_by") or None)

    return server
