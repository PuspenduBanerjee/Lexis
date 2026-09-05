"""Shared target-dispatch logic: pick the right emitter for a transpile request.

Used by both the CLI (`cli.py`) and the web API (`lexis_api`) so the mapping from
`--target` to an emitter lives in exactly one place.
"""

from dataclasses import dataclass

from lexis._vendor.ossie import OssieDocument
from lexis.resolved_model import ResolvedModel
from lexis.sml.emit import emit_sml_files
from lexis.transpilers.cube import emit_cube_yaml
from lexis.transpilers.dbt_ossie import emit_dbt_ossie_document
from lexis.transpilers.mcp import emit_mcp_tool_manifest
from lexis.transpilers.snowflake_semantic_view import emit_snowflake_semantic_view
from lexis.transpilers.sql import EMITTERS as SQL_EMITTERS

TARGETS = [*SQL_EMITTERS.keys(), "cube", "dbt", "mcp", "snowflake_semantic_view", "sml"]

# Short alternate spellings accepted alongside the canonical TARGETS name - resolved
# to the canonical name before dispatch, so callers/tests only ever need to branch on
# the canonical spelling below.
TARGET_ALIASES = {"ssv": "snowflake_semantic_view"}


@dataclass(frozen=True)
class TranspileResult:
    # `sml` is the one multi-file target - one YAML file per SML object - so
    # `content` is a `dict[str, str]` (relative filename -> content) there;
    # every other target still returns a single `str`.
    content: str | dict[str, str]
    warnings: list[str]


def transpile(
    document: OssieDocument,
    model: ResolvedModel,
    target: str,
    metric: str | None = None,
    group_by: list[str] | None = None,
) -> TranspileResult:
    """Emit `model` (parsed from `document`) in the given `target` format.

    Raises ValueError for a missing/unknown target or a missing metric on a SQL target.
    """
    target = TARGET_ALIASES.get(target, target)
    if target in SQL_EMITTERS:
        if not metric:
            raise ValueError(f"metric is required for target {target!r}")
        emitter = SQL_EMITTERS[target]()
        content = emitter.emit_metric_query(model, metric, group_by=group_by or None)
        return TranspileResult(content=content, warnings=[])
    elif target == "cube":
        return TranspileResult(content=emit_cube_yaml(model), warnings=[])
    elif target == "dbt":
        result = emit_dbt_ossie_document(document)
        return TranspileResult(content=result.artifact.content, warnings=result.warnings)
    elif target == "mcp":
        return TranspileResult(content=emit_mcp_tool_manifest(model), warnings=[])
    elif target == "snowflake_semantic_view":
        return TranspileResult(content=emit_snowflake_semantic_view(model), warnings=[])
    elif target == "sml":
        result = emit_sml_files(document)
        return TranspileResult(content=result.files, warnings=result.warnings)
    else:
        raise ValueError(f"Unknown target {target!r}")
