"""Ossie -> MCP tool manifest / LLM function-calling schema emitter.

This is Semantica's differentiator: turn a metric's `ai_context` (instructions,
synonyms, examples) into a grounded tool description, and constrain `group_by` to an
explicit enum of real dataset.field refs — so an agent gets a governed query tool
instead of having to guess joins/columns/synonyms from a bare warehouse schema.
"""

import json

from semantica._vendor.ossie import OssieAIContextObject, OssieDialect
from semantica.resolved_model import ResolvedModel


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


def build_metric_tool_specs(model: ResolvedModel) -> list[dict]:
    """One `{"name", "description", "inputSchema"}` dict per Ossie metric — the bare MCP
    tool schema, shared by the static manifest below and the live MCP server
    (`semantica.mcp_server`), which additionally needs plain schema dicts it can turn
    into `mcp.types.Tool` objects (no extra `_semantica`-style fields)."""
    dimension_refs = _dimension_refs(model)
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
                        }
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

        tools.append({**spec, "_semantica": {"metric": metric.name, "expression": expr}})

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
