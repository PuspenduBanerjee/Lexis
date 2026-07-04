"""Shared target-dispatch logic: pick the right emitter for a transpile request.

Used by both the CLI (`cli.py`) and the web API (`semantica_api`) so the mapping from
`--target` to an emitter lives in exactly one place.
"""

from dataclasses import dataclass

from semantica._vendor.osi import OSIDocument
from semantica.resolved_model import ResolvedModel
from semantica.transpilers.cube import emit_cube_yaml
from semantica.transpilers.dbt_osi import emit_dbt_osi_document
from semantica.transpilers.mcp import emit_mcp_tool_manifest
from semantica.transpilers.sql import EMITTERS as SQL_EMITTERS

TARGETS = [*SQL_EMITTERS.keys(), "cube", "dbt", "mcp"]


@dataclass(frozen=True)
class TranspileResult:
    content: str
    warnings: list[str]


def transpile(
    document: OSIDocument,
    model: ResolvedModel,
    target: str,
    metric: str | None = None,
    group_by: list[str] | None = None,
) -> TranspileResult:
    """Emit `model` (parsed from `document`) in the given `target` format.

    Raises ValueError for a missing/unknown target or a missing metric on a SQL target.
    """
    if target in SQL_EMITTERS:
        if not metric:
            raise ValueError(f"metric is required for target {target!r}")
        emitter = SQL_EMITTERS[target]()
        content = emitter.emit_metric_query(model, metric, group_by=group_by or None)
        return TranspileResult(content=content, warnings=[])
    elif target == "cube":
        return TranspileResult(content=emit_cube_yaml(model), warnings=[])
    elif target == "dbt":
        result = emit_dbt_osi_document(document)
        return TranspileResult(content=result.artifact.content, warnings=result.warnings)
    elif target == "mcp":
        return TranspileResult(content=emit_mcp_tool_manifest(model), warnings=[])
    else:
        raise ValueError(f"Unknown target {target!r}")
