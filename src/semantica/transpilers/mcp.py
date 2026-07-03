"""OSI -> MCP tool manifest / LLM function-calling schema emitter.

This is Semantica's differentiator: turn a metric's `ai_context` (instructions,
synonyms, examples) into a grounded tool description, and constrain `group_by` to an
explicit enum of real dataset.field refs — so an agent gets a governed query tool
instead of having to guess joins/columns/synonyms from a bare warehouse schema.
"""

import json

from semantica._vendor.osi import OSIAIContextObject, OSIDialect
from semantica.resolved_model import ResolvedModel


def _describe_ai_context(base_description: str | None, ai_context) -> str:
    parts = [base_description] if base_description else []
    if ai_context is None:
        pass
    elif isinstance(ai_context, str):
        parts.append(ai_context)
    elif isinstance(ai_context, OSIAIContextObject):
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


def build_mcp_tool_manifest(model: ResolvedModel) -> dict:
    """Build an MCP-style `{"tools": [...]}` manifest, one tool per OSI metric."""
    dimension_refs = _dimension_refs(model)
    tools = []

    for metric in model.metrics.values():
        description = _describe_ai_context(metric.description, metric.ai_context)
        try:
            expr = model.resolve_expression(metric.expression, OSIDialect.ANSI_SQL)
        except Exception:
            expr = None

        tool = {
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
            "_semantica": {
                "metric": metric.name,
                "expression": expr,
            },
        }
        tools.append(tool)

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
