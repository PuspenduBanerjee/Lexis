"""Package an OssieDocument for dbt-core 1.12+'s native Ossie ingestion.

dbt-core >=1.12 parses raw Ossie JSON files dropped in a project's `osi/` directory (or a
configured `osi-paths` — dbt kept this config key and default directory name lowercase
`osi` even after the upstream spec's Apache rename) directly into its manifest — no
Ossie->dbt-YAML conversion needed. Per dbt's docs
(docs.getdbt.com/docs/build/ossie-semantic-models, checked 2026-09-04), two hard
constraints apply that our own Ossie documents don't satisfy by default, so this module
adjusts/validates rather than passing the document through verbatim:

1. dbt only accepts `version: "0.1.0"` or `"0.1.1"` — any other version string is a
   parse error. Our vendored OssieDocument defaults to `"0.2.0.dev0"` (the current core
   spec draft version), so the emitted copy's version is overridden to `"0.1.1"`; the
   document shape (datasets/fields/relationships/metrics) is otherwise unchanged.
2. Each dataset's `source` must be `database.schema.alias`, fully qualified to a dbt
   model *in the target dbt project* (not a source/seed/snapshot/external table). We
   can't verify this against a project we don't have, so we only check the shape
   (three dot-separated parts) and surface a warning for anything that doesn't match.
"""

import json
from dataclasses import dataclass

from lexis._vendor.ossie import OssieDocument
from lexis.transpilers.base import Artifact

DBT_SUPPORTED_OSSIE_VERSIONS = ("0.1.0", "0.1.1")
DBT_EMIT_VERSION = "0.1.1"


@dataclass(frozen=True)
class DbtOssieResult:
    artifact: Artifact
    warnings: list[str]


def _source_shape_warnings(document: OssieDocument) -> list[str]:
    warnings = []
    for semantic_model in document.semantic_model:
        for dataset in semantic_model.datasets:
            parts = dataset.source.split(".")
            if len(parts) != 3:
                warnings.append(
                    f"dataset {dataset.name!r} source {dataset.source!r} is not "
                    "'database.schema.alias' — dbt requires it resolve to a dbt model "
                    "in the target project; this dataset will likely fail to parse "
                    "under dbt-core's Ossie ingestion until corrected."
                )
    return warnings


def emit_dbt_ossie_document(document: OssieDocument, filename: str = "osi/lexis_model.json") -> DbtOssieResult:
    """Render `document` as a dbt-core-1.12+-compatible Ossie JSON artifact."""
    data = document.model_dump(by_alias=True, exclude_none=True, mode="json")
    data["version"] = DBT_EMIT_VERSION

    warnings = list(_source_shape_warnings(document))
    if document.version not in DBT_SUPPORTED_OSSIE_VERSIONS:
        warnings.append(
            f"source document version {document.version!r} is not dbt-supported "
            f"({DBT_SUPPORTED_OSSIE_VERSIONS!r}); emitted copy overrides version to "
            f"{DBT_EMIT_VERSION!r} — verify the document's constructs are still valid "
            "under the 0.1.x Ossie schema before relying on this in dbt."
        )

    content = json.dumps(data, indent=2) + "\n"
    return DbtOssieResult(artifact=Artifact(filename=filename, content=content), warnings=warnings)
