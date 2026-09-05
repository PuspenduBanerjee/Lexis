"""Shared helpers for the Ossie <-> SML converter.

Mirrors the conventions Apache Ossie's other bidirectional converters already
established (third_party/ossie/converters/{omni,orionbelt,databricks}/src/*/_common.py):
a `custom_extensions` stash protocol keyed by vendor name, a `ConversionError` for
clean error messages, and a dialect-preference table. See SML_OSSIE_CONVERTER_PLAN.md
at the repo root for the full data-model mapping this implements.
"""

import json
import re
from typing import Any, NamedTuple, Optional

from lexis._vendor.ossie import OssieCustomExtension, OssieDataType, OssieDialect

VENDOR = "SML"

# Bump when the shape of a stashed `data` blob changes.
STASH_VERSION = 1

# SML SQL dialects this converter maps to/from a corresponding Ossie dialect.
# Postgresql and Iris have no Ossie enum slot (see SML_OSSIE_CONVERTER_PLAN.md,
# Edge Case #9): never emitted on Ossie -> SML; preserved via stash on SML -> Ossie
# (parse.py, phase 2).
SML_TO_OSSIE_DIALECT = {
    "Snowflake": OssieDialect.SNOWFLAKE,
    "DatabricksSQL": OssieDialect.DATABRICKS,
    "BigQuery": OssieDialect.BIGQUERY,
}
OSSIE_TO_SML_DIALECT = {v: k for k, v in SML_TO_OSSIE_DIALECT.items()}

# OssieDataType -> a plausible SML `data_type` string. SML's docs show free-form
# examples (e.g. "decimal(7,2)") rather than a strict enum, so this is a
# reasonable default, not a spec-mandated mapping.
OSSIE_TO_SML_DATATYPE = {
    OssieDataType.STRING: "string",
    OssieDataType.INTEGER: "int",
    OssieDataType.DECIMAL: "decimal(18,2)",
    OssieDataType.FLOAT: "double",
    OssieDataType.BOOLEAN: "boolean",
    OssieDataType.DATE: "date",
    OssieDataType.TIME: "time",
    OssieDataType.DATE_TIME: "datetime",
    OssieDataType.DATE_TIME_TZ: "datetime",
    OssieDataType.OPAQUE: "string",
}


def sml_datatype_to_ossie(data_type: Optional[str]) -> Optional[OssieDataType]:
    """Best-effort reverse of OSSIE_TO_SML_DATATYPE. SML's `data_type` is
    free-form (e.g. "decimal(7,2)", "varchar(50)") rather than a strict enum, so
    this matches on a lowercased prefix rather than exact equality. Returns None
    (rather than guessing) for anything unrecognized - the Ossie field is simply
    emitted with no `datatype`."""
    if not data_type:
        return None
    lowered = data_type.strip().lower()
    if lowered.startswith(("decimal", "numeric")):
        return OssieDataType.DECIMAL
    if lowered.startswith(("double", "float", "real")):
        return OssieDataType.FLOAT
    if lowered.startswith(("int", "bigint", "smallint", "tinyint")):
        return OssieDataType.INTEGER
    if lowered.startswith(("bool",)):
        return OssieDataType.BOOLEAN
    if lowered.startswith("datetime") or lowered.startswith("timestamp"):
        return OssieDataType.DATE_TIME
    if lowered.startswith("date"):
        return OssieDataType.DATE
    if lowered.startswith("time"):
        return OssieDataType.TIME
    if lowered.startswith(("string", "varchar", "char", "text")):
        return OssieDataType.STRING
    return None


class ConversionError(Exception):
    """Raised when an input cannot be converted."""


def require(obj: dict, key: str, what: str) -> Any:
    """Return `obj[key]`, or raise a clean ConversionError if it's missing/empty."""
    if not isinstance(obj, dict) or key not in obj or obj[key] is None:
        raise ConversionError(f"{what} is missing required {key!r}")
    value = obj[key]
    if isinstance(value, str) and not value.strip():
        raise ConversionError(f"{what} has an empty {key!r}")
    return value


def read_stash(obj: Any) -> dict:
    """Return the SML `custom_extensions` stash dict on an Ossie object (anything
    with a `custom_extensions` attribute - Dataset/Field/Relationship/Metric/
    SemanticModel), or {} if absent. Strips the `_v` version marker.

    Phase 1 (Ossie -> SML) never encounters real stash data yet, since nothing has
    written an SML stash - this exists so Phase 2's SML -> Ossie -> SML round trip
    can reconstruct richer SML shapes once `parse.py` starts writing one.
    """
    for ext in getattr(obj, "custom_extensions", None) or []:
        if ext.vendor_name == VENDOR:
            try:
                data = json.loads(ext.data)
            except json.JSONDecodeError as e:
                raise ConversionError(f"SML custom_extensions data is not valid JSON: {e}") from e
            data.pop("_v", None)
            return data
    return {}


def make_stash_extension(data: dict) -> OssieCustomExtension:
    """Build an OssieCustomExtension carrying `data` under the SML vendor tag."""
    payload = {"_v": STASH_VERSION, **data}
    return OssieCustomExtension(vendor_name=VENDOR, data=json.dumps(payload))


# calculation_method (SML) <-> SQL aggregate function name. Extends the same
# pattern already used for the Cube.js emitter (transpilers/cube.py's
# _SIMPLE_AGGREGATE_RE) with SML's fuller calculation_method vocabulary.
# `sum distinct` and `estimated count distinct` have no single ANSI function and
# are intentionally left unmapped (see SML_OSSIE_CONVERTER_PLAN.md Edge Cases).
CALC_METHOD_TO_SQL_FUNC = {
    "sum": "SUM",
    "average": "AVG",
    "count non-null": "COUNT",
    "maximum": "MAX",
    "minimum": "MIN",
    "stddev_pop": "STDDEV_POP",
    "stddev_samp": "STDDEV_SAMP",
    "var_pop": "VAR_POP",
    "var_samp": "VAR_SAMP",
    "percentile": "PERCENTILE_CONT",
    "count_if": "COUNT_IF",
}
_SQL_FUNC_TO_CALC_METHOD = {v: k for k, v in CALC_METHOD_TO_SQL_FUNC.items()}

_SIMPLE_AGGREGATE_RE = re.compile(
    r"^(SUM|AVG|COUNT|MIN|MAX|STDDEV_POP|STDDEV_SAMP|VAR_POP|VAR_SAMP|COUNT_IF)"
    r"\s*\(\s*(DISTINCT\s+)?([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\)$",
    re.IGNORECASE,
)


def decompose_simple_aggregate(expr: str) -> Optional[tuple[str, str, str]]:
    """Match `FUNC([DISTINCT] dataset.column)` and return
    `(calculation_method, dataset, column)`, or None if `expr` isn't that shape."""
    match = _SIMPLE_AGGREGATE_RE.match(expr.strip())
    if not match:
        return None
    func, distinct, dataset, column = match.groups()
    func = func.upper()
    if distinct:
        if func != "COUNT":
            return None  # DISTINCT on a non-COUNT aggregate has no SML calculation_method
        method = "count distinct"
    else:
        method = _SQL_FUNC_TO_CALC_METHOD.get(func)
        if method is None:
            return None
    return method, dataset, column


def synthesize_aggregate_sql(calculation_method: str, dataset: str, column: str) -> Optional[str]:
    """Reverse of decompose_simple_aggregate: build `FUNC(dataset.column)` ANSI SQL
    for a calculation_method. Returns None for methods with no single ANSI function."""
    if calculation_method == "count distinct":
        return f"COUNT(DISTINCT {dataset}.{column})"
    func = CALC_METHOD_TO_SQL_FUNC.get(calculation_method)
    return f"{func}({dataset}.{column})" if func else None


class RatioAggregate(NamedTuple):
    """A `numerator / denominator` metric where both sides are simple
    `FUNC(dataset.column)` aggregates - the exact shape SML's own metric_calc docs
    use for ratio metrics (`"[Measures].[a]/[Measures].[b]"`)."""

    numerator: tuple[str, str, str]  # (calculation_method, dataset, column)
    denominator: tuple[str, str, str]
    denominator_nullif_guard_dropped: bool


_NULLIF_ZERO_RE = re.compile(r"^NULLIF\s*\(\s*(.+?)\s*,\s*0\s*\)$", re.IGNORECASE)


def _split_top_level_slash(expr: str) -> Optional[tuple[str, str]]:
    """Split `expr` on the first `/` that isn't nested inside parentheses.
    Returns None if there's no such split point (so `A / B / C` correctly fails to
    decompose here rather than silently dropping the third term)."""
    depth = 0
    for i, ch in enumerate(expr):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "/" and depth == 0:
            return expr[:i], expr[i + 1 :]
    return None


def decompose_ratio_aggregate(expr: str) -> Optional[RatioAggregate]:
    """Match `AGG(dataset.column) / AGG(dataset.column)`, optionally with a
    `NULLIF(..., 0)` divide-by-zero guard around the denominator (a common SQL
    idiom with no MDX equivalent - MDX division already returns blank/error on
    divide-by-zero). Returns None if `expr` isn't that shape."""
    split = _split_top_level_slash(expr.strip())
    if split is None:
        return None
    left, right = split[0].strip(), split[1].strip()

    numerator = decompose_simple_aggregate(left)
    if numerator is None:
        return None

    nullif_guard = False
    nullif_match = _NULLIF_ZERO_RE.match(right)
    if nullif_match:
        right = nullif_match.group(1)
        nullif_guard = True

    denominator = decompose_simple_aggregate(right)
    if denominator is None:
        return None

    return RatioAggregate(numerator=numerator, denominator=denominator, denominator_nullif_guard_dropped=nullif_guard)
