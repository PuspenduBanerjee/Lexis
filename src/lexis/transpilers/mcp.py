"""Ossie -> MCP tool manifest / LLM function-calling schema emitter.

This is Lexis's differentiator: turn a metric's `ai_context` (instructions,
synonyms, examples) into a grounded tool description, and constrain `group_by` to an
explicit enum of real dataset.field refs — so an agent gets a governed query tool
instead of having to guess joins/columns/synonyms from a bare warehouse schema.
"""

import json

from lexis._vendor.ossie import OssieAIContextObject, OssieDataType, OssieDialect
from lexis.resolved_model import ResolvedModel
from lexis.transpilers.sql.base import SqlDialectEmitter

#: Grains a `query_<metric>` tool call may bucket by (see `time_grain` below).
#: Kept in sync with `SqlDialectEmitter.TIME_GRAINS`, ordered fine -> coarse for the
#: tool schema (an agent picking "the smallest useful bucket" reads top-down).
TIME_GRAINS = ["day", "week", "month", "quarter", "year"]
assert set(TIME_GRAINS) == set(SqlDialectEmitter.TIME_GRAINS)

_DATE_DATATYPES = frozenset(
    {OssieDataType.DATE, OssieDataType.DATE_TIME, OssieDataType.DATE_TIME_TZ}
)


def time_axis_refs(model: ResolvedModel) -> list[str]:
    """`dataset.field` refs usable as the time axis of a `DATE_TRUNC`-bucketed
    query: fields whose Ossie `datatype` is a date/timestamp. Falls back to any
    `is_time` dimension when the model declares no temporal datatypes at all, so
    hand-written models that skip `datatype` still get weekly/monthly grains."""
    dated: list[str] = []
    is_time: list[str] = []
    for dataset_name, dataset in model.datasets.items():
        for f in dataset.fields or []:
            ref = f"{dataset_name}.{f.name}"
            if f.datatype in _DATE_DATATYPES:
                dated.append(ref)
            elif f.is_time_dimension():
                is_time.append(ref)
    return dated or is_time


def resolve_time_axis(model: ResolvedModel, time_field: str | None) -> tuple[str, str]:
    """`(time_dataset, time_field)` for a `time_grain` query. Uses `time_field` when
    given (validated against `time_axis_refs`), otherwise the model's sole time axis.
    Raises `ValueError` (a clean MCP tool error) when there's no time axis, more than
    one and none was chosen, or an unknown one was passed."""
    refs = time_axis_refs(model)
    if not refs:
        raise ValueError("this model has no date field to bucket by, so time_grain is not supported")
    if time_field is None:
        if len(refs) > 1:
            raise ValueError(f"time_field is required when time_grain is set; choose one of {refs}")
        time_field = refs[0]
    elif time_field not in refs:
        raise ValueError(f"unknown time_field {time_field!r}; choose one of {refs}")
    dataset, _, column = time_field.partition(".")
    return dataset, column


def model_instructions(model: ResolvedModel) -> str:
    """The model-level `ai_context` text (instructions / synonyms / examples), if any -
    surfaced to MCP clients as the server's `instructions` and in `list_metrics`, so a
    model can e.g. tell an agent its weeks are Sunday-Saturday retail weeks rather than
    ISO Monday weeks. Returns "" when the model has no `ai_context` (the model
    `description` is carried separately, by `list_models`)."""
    return _describe_ai_context(None, model.semantic_model.ai_context)


def _describe_ai_context(base_description: str | None, ai_context) -> str:
    parts = [base_description] if base_description else []
    if ai_context is None:
        pass
    elif isinstance(ai_context, str):
        parts.append(ai_context)
    elif isinstance(ai_context, OssieAIContextObject):
        if ai_context.instructions:
            parts.append(ai_context.instructions)
        if ai_context.synonyms:
            parts.append("Also known as: " + ", ".join(ai_context.synonyms) + ".")
        if ai_context.examples:
            parts.append("Example questions: " + " | ".join(ai_context.examples))
    return " ".join(p.strip() for p in parts if p and p.strip())


def _dimension_refs(model: ResolvedModel) -> list[str]:
    refs = []
    for dataset_name, dataset in model.datasets.items():
        for f in dataset.fields or []:
            refs.append(f"{dataset_name}.{f.name}")
    return refs


def _time_bucketing_properties(time_refs: list[str]) -> dict:
    """The `time_grain` / `time_field` input-schema properties, added to every
    `query_<metric>` tool when the model has at least one usable time axis."""
    default_hint = (
        f" Defaults to {time_refs[0]!r}." if len(time_refs) == 1
        else " Required when time_grain is set (the model has more than one time field)."
    )
    return {
        "time_grain": {
            "type": "string",
            "enum": TIME_GRAINS,
            "description": (
                "Return one row per consecutive time period instead of a single total - "
                "e.g. 'week' for a week-by-week trend. Periods are ISO 8601 calendar "
                "periods and weeks start Monday; if this model's instructions define a "
                "fiscal or retail week, label the results accordingly. Cannot be combined "
                "with group_by."
            ),
        },
        "time_field": {
            "type": "string",
            "enum": time_refs,
            "description": "Which date field to bucket by when time_grain is set." + default_hint,
        },
    }


def build_metric_tool_specs(model: ResolvedModel) -> list[dict]:
    """One `{"name", "description", "inputSchema"}` dict per Ossie metric — the bare MCP
    tool schema, shared by the static manifest below and the live MCP server
    (`lexis.mcp_server`), which additionally needs plain schema dicts it can turn
    into `mcp.types.Tool` objects (no extra `_lexis`-style fields)."""
    dimension_refs = _dimension_refs(model)
    time_refs = time_axis_refs(model)
    time_properties = _time_bucketing_properties(time_refs) if time_refs else {}
    specs = []

    for metric in model.metrics.values():
        description = _describe_ai_context(metric.description, metric.ai_context)
        specs.append(
            {
                "name": f"query_{metric.name}",
                "description": description or f"Query the {metric.name!r} metric.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "group_by": {
                            "type": "array",
                            "items": {"type": "string", "enum": dimension_refs},
                            "description": (
                                "Zero or more dataset.field references to group results by."
                            ),
                        },
                        **time_properties,
                    },
                    "additionalProperties": False,
                },
            }
        )

    return specs


def build_mcp_tool_manifest(model: ResolvedModel) -> dict:
    """Build an MCP-style `{"tools": [...]}` manifest, one tool per Ossie metric."""
    tools = []

    for metric, spec in zip(model.metrics.values(), build_metric_tool_specs(model), strict=True):
        try:
            expr = model.resolve_expression(metric.expression, OssieDialect.ANSI_SQL)
        except Exception:
            expr = None

        tools.append({**spec, "_lexis": {"metric": metric.name, "expression": expr}})

    return {
        "model": {
            "name": model.semantic_model.name,
            "description": _describe_ai_context(
                model.semantic_model.description, model.semantic_model.ai_context
            ),
        },
        "tools": tools,
    }


def emit_mcp_tool_manifest(model: ResolvedModel) -> str:
    """Render the MCP tool manifest as JSON text."""
    return json.dumps(build_mcp_tool_manifest(model), indent=2) + "\n"
