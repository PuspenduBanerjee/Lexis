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

from lexis._vendor.ossie import OssieDialect
from lexis.resolved_model import ResolvedModel
from lexis.transpilers.mcp import build_metric_tool_specs, model_instructions, resolve_time_axis
from lexis.transpilers.sql.base import SqlDialectEmitter

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
    `lexis_api.query_runtime.run_metric_query`, duplicated here (rather than
    imported) so this core module stays free of the `lexis_api` (FastAPI/
    SQLAlchemy) dependency chain; both copies are small enough that the duplication
    is cheaper than relocating that module."""
    sql = emitter.emit_metric_query(model, metric, group_by=group_by)
    return _run(con, sql)


def _run(con: Any, sql: str) -> dict:
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


def run_timeseries_query(
    con: Any,
    emitter: SqlDialectEmitter,
    model: ResolvedModel,
    metric: str,
    time_dataset: str,
    time_field: str,
    grain: str,
) -> dict:
    """`metric` bucketed by `DATE_TRUNC(grain, time_dataset.time_field)`, one row per
    period. Core mirror of `lexis_api.query_runtime.run_timeseries_query` (drill-down
    filters omitted - the MCP tool doesn't expose them)."""
    sql = emitter.emit_timeseries_query(model, metric, time_dataset, time_field, grain)
    return _run(con, sql)


def query_datasets(
    model: ResolvedModel,
    metric: str,
    group_by: list[str] | None,
    time_grain: str | None = None,
    time_field: str | None = None,
) -> set[str]:
    """Every dataset a `run_metric_or_timeseries` call touches - the caller passes
    this to its connection opener so a duckdb_file connection ATTACHes the right
    files first."""
    metric_expr = model.resolve_expression(model.metrics[metric].expression, OssieDialect.ANSI_SQL)
    datasets = set(model.referenced_datasets(metric_expr))
    if time_grain:
        datasets.add(resolve_time_axis(model, time_field)[0])
    else:
        datasets |= {ref.split(".", 1)[0] for ref in (group_by or [])}
    return datasets


def run_metric_or_timeseries(
    con: Any,
    emitter: SqlDialectEmitter,
    model: ResolvedModel,
    metric: str,
    group_by: list[str] | None,
    time_grain: str | None = None,
    time_field: str | None = None,
) -> dict:
    """Dispatch a `query_<metric>` tool call: a `DATE_TRUNC`-bucketed timeseries when
    `time_grain` is set, otherwise a plain (optionally grouped) total. Raises
    `ValueError` (a clean MCP tool error) on an unsupported combination."""
    if time_grain:
        if group_by:
            raise ValueError("time_grain and group_by cannot be combined in one query yet")
        time_dataset, column = resolve_time_axis(model, time_field)
        return run_timeseries_query(con, emitter, model, metric, time_dataset, column, time_grain)
    return run_metric_query(con, emitter, model, metric, group_by)


# execute(metric, group_by, time_grain, time_field) -> result dict. `time_grain`
# (day/week/month/quarter/year) buckets the metric into consecutive periods via the
# emitter's timeseries query instead of a single total; `time_field` picks the date
# axis (see lexis.transpilers.mcp.resolve_time_axis). Both None for a plain total.
ExecuteMetric = Callable[[str, list[str] | None, str | None, str | None], dict]


def build_server(model: ResolvedModel, execute: ExecuteMetric, name: str | None = None) -> Server:
    """Build an MCP `Server` with one `query_<metric>` tool per Ossie metric, dispatching
    tool calls to `execute(metric_name, group_by, time_grain, time_field)`."""
    tools = [types.Tool(**spec) for spec in build_metric_tool_specs(model)]
    server: Server = Server(
        name or model.semantic_model.name, instructions=model_instructions(model) or None
    )

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
        return await anyio.to_thread.run_sync(
            execute,
            metric,
            arguments.get("group_by") or None,
            arguments.get("time_grain"),
            arguments.get("time_field"),
        )

    return server
