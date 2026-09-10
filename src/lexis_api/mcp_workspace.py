"""Workspace-wide MCP server: model_id/connection_id are supplied as tool-call
arguments instead of being fixed in the connection URL (contrast with
`lexis.mcp_server.build_server`, which is scoped to one model+connection at
construction time - see `routers/mcp.py`'s per-model endpoint).

This trades that server's governed one-`query_<metric>`-tool-per-metric design
for a smaller, generic tool set (`list_models`, `list_connections`,
`list_metrics`, `query_metric`) so a single long-lived client connection can
query any model+connection the caller can see without reconnecting to a
different URL. `list_metrics` still surfaces each metric's description and
valid `group_by` references as real data (the same data
`transpilers/mcp.build_metric_tool_specs` would have baked into a fixed tool
schema) - just discoverable per call instead of enforced by the tool's JSON
schema, since the schema can't depend on which `model_id` argument shows up in
a given call.
"""

from typing import Any

import anyio
from fastapi import HTTPException
from mcp import types
from mcp.server.lowlevel import Server
from sqlalchemy.orm import Session

from lexis.mcp_server import query_datasets, run_metric_or_timeseries
from lexis.parser import parse_ossie_yaml
from lexis.resolved_model import ResolvedModel
from lexis.transpilers.mcp import (
    TIME_GRAINS,
    build_metric_tool_specs,
    model_instructions,
    time_axis_refs,
)
from lexis_api.connection_runtime import emitter_for_connection_type, open_connection
from lexis_api.deps import find_connection_or_404, find_model_or_404
from lexis_api.models import Connection, SemanticModelRecord

_TOOLS = [
    types.Tool(
        name="list_models",
        description="List every semantic model available in this Lexis workspace.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    types.Tool(
        name="list_connections",
        description="List every data connection available to run queries against.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    types.Tool(
        name="list_metrics",
        description=(
            "List a model's metrics - name, description, and valid group_by "
            "references - before calling query_metric against it."
        ),
        inputSchema={
            "type": "object",
            "properties": {"model_id": {"type": "integer", "description": "a model id from list_models"}},
            "required": ["model_id"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="query_metric",
        description=(
            "Run a metric query against a specific model and connection: either a "
            "single total (optionally grouped by dimension references) or, with "
            "time_grain, one row per consecutive time period. Call list_models, "
            "list_connections, and list_metrics first to find valid ids/names, valid "
            "group_by / time_field values, and any model-specific week conventions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "model_id": {"type": "integer", "description": "a model id from list_models"},
                "metric": {"type": "string", "description": "a metric name from list_metrics"},
                "connection_id": {"type": "integer", "description": "a connection id from list_connections"},
                "group_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "dataset.field references to group by - see list_metrics for valid ones",
                },
                "time_grain": {
                    "type": "string",
                    "enum": TIME_GRAINS,
                    "description": (
                        "Bucket the metric into consecutive periods instead of one total "
                        "(e.g. 'week'). ISO 8601 periods, weeks start Monday unless the "
                        "model's instructions say otherwise. Cannot be combined with group_by."
                    ),
                },
                "time_field": {
                    "type": "string",
                    "description": (
                        "dataset.field date axis for time_grain - see list_metrics "
                        "(time_fields); optional when the model has exactly one"
                    ),
                },
            },
            "required": ["model_id", "metric", "connection_id"],
            "additionalProperties": False,
        },
    ),
]


def _resolved_model(db: Session, model_id: int) -> tuple[SemanticModelRecord, ResolvedModel]:
    record = find_model_or_404(db, model_id)
    document = parse_ossie_yaml(record.raw_yaml)
    return record, ResolvedModel.build(document.semantic_model[0])


def _list_models(db: Session) -> dict[str, Any]:
    records = db.query(SemanticModelRecord).order_by(SemanticModelRecord.id).all()
    models = []
    for record in records:
        semantic_model = parse_ossie_yaml(record.raw_yaml).semantic_model[0]
        models.append({"id": record.id, "name": record.name, "description": semantic_model.description})
    return {"models": models}


def _list_connections(db: Session) -> dict[str, Any]:
    records = db.query(Connection).order_by(Connection.id).all()
    return {"connections": [{"id": r.id, "name": r.name, "type": r.type.value} for r in records]}


def _list_metrics(db: Session, model_id: int) -> dict[str, Any]:
    _, model = _resolved_model(db, model_id)
    metrics = []
    for spec in build_metric_tool_specs(model):
        group_by = spec["inputSchema"]["properties"]["group_by"]["items"]["enum"]
        metrics.append(
            {"name": spec["name"].removeprefix("query_"), "description": spec["description"], "group_by": group_by}
        )
    result: dict[str, Any] = {"metrics": metrics, "time_grains": TIME_GRAINS, "time_fields": time_axis_refs(model)}
    instructions = model_instructions(model)
    if instructions:
        result["instructions"] = instructions
    return result


def _query_metric(
    db: Session,
    model_id: int,
    metric: str,
    connection_id: int,
    group_by: list[str] | None,
    time_grain: str | None = None,
    time_field: str | None = None,
) -> dict:
    _, model = _resolved_model(db, model_id)
    if metric not in model.metrics:
        raise ValueError(f"unknown metric {metric!r} for model {model_id}")
    conn = find_connection_or_404(db, connection_id)
    emitter = emitter_for_connection_type(conn.type)
    referenced = query_datasets(model, metric, group_by, time_grain, time_field)
    with open_connection(conn, model, referenced) as con:
        return run_metric_or_timeseries(con, emitter, model, metric, group_by, time_grain, time_field)


def build_workspace_server(db: Session) -> Server:
    """Build the workspace-wide MCP `Server`. `db` is the caller's request-scoped
    session (see `routers/mcp.py`) - every tool call in this session shares it."""
    server: Server = Server(
        "lexis-workspace",
        instructions=(
            "Query governed semantic models. Flow: list_models -> list_connections -> "
            "list_metrics(model_id) -> query_metric. list_metrics returns each model's "
            "valid group_by refs, time_fields for time_grain queries, and any "
            "model-specific instructions (e.g. a non-ISO retail week)."
        ),
    )

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return _TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict:
        def run() -> dict:
            if name == "list_models":
                return _list_models(db)
            if name == "list_connections":
                return _list_connections(db)
            if name == "list_metrics":
                return _list_metrics(db, arguments["model_id"])
            if name == "query_metric":
                return _query_metric(
                    db,
                    arguments["model_id"],
                    arguments["metric"],
                    arguments["connection_id"],
                    arguments.get("group_by") or None,
                    arguments.get("time_grain"),
                    arguments.get("time_field"),
                )
            raise ValueError(f"unknown tool {name!r}")

        # Offload the blocking DB/query-execution work, same as build_server's
        # single-model `execute` closure - matters most for the HTTP transport,
        # which isn't already running inside FastAPI's own sync-endpoint threadpool.
        try:
            return await anyio.to_thread.run_sync(run)
        except HTTPException as exc:
            # HTTPException is a FastAPI/Starlette request-handling type, not
            # something the MCP SDK's error serialization knows about - translate
            # it to a plain exception so the tool call surfaces a clean error
            # instead of an unhandled type leaking out of this handler.
            raise ValueError(str(exc.detail)) from exc

    return server
