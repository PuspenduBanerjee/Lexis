"""Emit an OssieDocument as Snowflake Cortex Analyst semantic model YAML.

Thin adapter around the vendored `ossie_snowflake` converter (see
src/lexis/_vendor/ossie_converters/NOTICE.md for its commit pin) - the
document is serialized back to Ossie YAML and handed to the vendored
converter unchanged, so conversion behavior tracks upstream exactly; this
module only adapts its calling convention (a raw YAML string in, warnings via
the stdlib `warnings` module out) to Lexis's own Artifact/warnings-list
transpiler contract.

Distinct from `snowflake_semantic_view.py` (which emits `CREATE SEMANTIC VIEW`
DDL) - this targets Cortex Analyst's own YAML spec instead.
"""

import warnings
from dataclasses import dataclass

from lexis._vendor.ossie import OssieDocument
from lexis._vendor.ossie_converters.ossie_snowflake.converter import (
    OssieConversionError,
    convert_ossie_to_snowflake,
)
from lexis.transpilers.base import Artifact


class SnowflakeCortexAnalystConversionError(ValueError):
    """Raised when `document` can't be converted to Cortex Analyst YAML."""


@dataclass(frozen=True)
class SnowflakeCortexAnalystResult:
    artifact: Artifact
    warnings: list[str]


def emit_snowflake_cortex_analyst(
    document: OssieDocument, filename: str = "cortex_analyst_semantic_model.yaml"
) -> SnowflakeCortexAnalystResult:
    """Render `document` as Snowflake Cortex Analyst semantic model YAML."""
    ossie_yaml = document.to_ossie_yaml()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            content = convert_ossie_to_snowflake(ossie_yaml)
        except OssieConversionError as exc:
            raise SnowflakeCortexAnalystConversionError(str(exc)) from exc
        collected = [str(w.message) for w in caught]

    return SnowflakeCortexAnalystResult(
        artifact=Artifact(filename=filename, content=content), warnings=collected
    )
