"""SML (Semantic Modeling Language) -> Ossie parser.

Reads a directory of `*.yml` SML files (one object per file, discriminated by
`object_type`, resolved through a global `unique_name` registry rather than a
folder layout - see SML_OSSIE_CONVERTER_PLAN.md at the repo root) and produces
one OssieDocument.

Flattening strategy (Ossie has no dimension/hierarchy concept at all):

- `connection` + `dataset` -> `OssieDataset` (`database.schema.table` source,
  same convention as `emit.py`'s reverse).
- Every `dimension.level_attributes[]` entry (the one joinable key attribute
  per level) and every `hierarchy.levels[].secondary_attributes[]` entry (per
  SML's own spec, these are fully inlined attribute objects, not name
  references) becomes a plain `OssieField` on whichever dataset *it* names -
  not necessarily the "same" dataset for every attribute of one dimension,
  which is what makes a snowflaked dimension fall out for free. The
  hierarchy/level grouping itself (order, multiple hierarchies, calculation
  groups) has no Ossie equivalent and is discarded from every Ossie-side
  consumer's perspective, but is stashed under `custom_extensions` so a later
  Ossie -> SML re-emission of *this same document* could reconstruct it.
- `model.relationships[]` (fact -> dimension) and every `dimension.relationships[]`
  (snowflake/embedded joins between a dimension's own backing datasets) share
  the exact same `{from: {dataset, join_columns}, to: {dimension, level}}`
  shape and are resolved identically: `to.level` is looked up in that
  dimension's `level_attributes` to find the backing dataset + key columns.
- `metric` -> `AGG(dataset.column)` ANSI_SQL (reverse of `synthesize_aggregate_sql`).
  `metric_calc` -> the `"[Measures].[a]/[Measures].[b]"` ratio shape this
  converter's own Ossie -> SML direction emits is decomposed back into
  `a_sql / b_sql` ANSI_SQL; any other MDX is passed through verbatim under
  Ossie's `MDX` dialect slot (never translated, per SML_OSSIE_CONVERTER_PLAN.md
  Edge Case #2).
- Object types with no Ossie equivalent at all (`row_security`, `perspectives`,
  `composite_model`, `package`, ...) and model/catalog-level fields this
  converter doesn't interpret (`perspectives`, `drillthroughs`, `aggregates`,
  `partitions`, `overrides`, ...) are preserved opaquely under
  `custom_extensions` rather than silently dropped.

v1 scope requires exactly one `catalog` and one `model` object - multi-model/
composite repos are not supported (see SML_OSSIE_CONVERTER_PLAN.md Edge Case #8).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from lexis._vendor.ossie import OssieDocument
from lexis.sml._common import (
    ConversionError,
    make_stash_extension,
    require,
    sml_datatype_to_ossie,
    synthesize_aggregate_sql,
)

# object_types this converter interprets functionally; anything else has no
# Ossie equivalent and is stashed opaquely (see module docstring).
_SUPPORTED_OBJECT_TYPES = {"catalog", "connection", "dataset", "dimension", "metric", "metric_calc", "model"}

# The one MDX shape this converter's own Ossie -> SML direction produces for a
# ratio metric (see emit.py) - decomposed back into ANSI_SQL when both operands
# resolve to already-converted metrics.
_RATIO_MDX_RE = re.compile(r"^\[Measures\]\.\[(?P<numerator>.+)\]\s*/\s*\[Measures\]\.\[(?P<denominator>.+)\]$")

# model/catalog fields this converter itself sets or reads; anything else on
# those two object types (perspectives, drillthroughs, aggregates, partitions,
# overrides, dataset_properties, ...) is stashed rather than dropped.
_HANDLED_MODEL_FIELDS = {"unique_name", "object_type", "label", "description", "relationships", "metrics"}
_HANDLED_CATALOG_FIELDS = {"unique_name", "object_type", "label", "description"}


@dataclass(frozen=True)
class SmlParseResult:
    document: OssieDocument
    warnings: list[str]


def _load_objects(directory: Path) -> dict[str, dict[str, dict]]:
    """Read every `*.yml` under `directory`, grouped by object_type then unique_name."""
    by_type: dict[str, dict[str, dict]] = {}
    for path in sorted(directory.rglob("*.yml")):
        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict):
            continue
        object_type = require(raw, "object_type", f"{path}")
        name = require(raw, "unique_name", f"{path} ({object_type})")
        bucket = by_type.setdefault(object_type, {})
        if name in bucket:
            raise ConversionError(f"duplicate unique_name {name!r} for object_type {object_type!r}")
        bucket[name] = raw
    return by_type


def parse_sml_repo(directory: str | Path) -> SmlParseResult:
    """Parse an SML repo directory into a single OssieDocument."""
    by_type = _load_objects(Path(directory))
    warnings: list[str] = []

    unsupported_objects: dict[str, dict] = {}
    for object_type in sorted(set(by_type) - _SUPPORTED_OBJECT_TYPES):
        for name, raw in by_type[object_type].items():
            unsupported_objects[name] = raw
            warnings.append(
                f"LOSSY: {object_type} {name!r} has no Ossie equivalent; preserved opaquely under "
                "custom_extensions but not interpreted by any Ossie-side consumer."
            )

    catalogs = by_type.get("catalog", {})
    models = by_type.get("model", {})
    if len(catalogs) != 1:
        raise ConversionError(f"expected exactly one catalog object, found {len(catalogs)}")
    if len(models) != 1:
        raise ConversionError(
            "expected exactly one model object - multi-model/composite repos are not supported "
            "in v1 (see SML_OSSIE_CONVERTER_PLAN.md Edge Case #8)"
        )
    catalog = next(iter(catalogs.values()))
    model = next(iter(models.values()))

    connections = by_type.get("connection", {})
    datasets_raw = by_type.get("dataset", {})
    dimensions_raw = by_type.get("dimension", {})
    metrics_raw = by_type.get("metric", {})
    metric_calcs_raw = by_type.get("metric_calc", {})

    # --- dataset source (database.schema.table) ---
    dataset_source: dict[str, str] = {}
    for name, raw in datasets_raw.items():
        conn_id, table = raw.get("connection_id"), raw.get("table")
        if not conn_id or not table:
            warnings.append(
                f"LOSSY: dataset {name!r} has no connection_id/table (a query dataset with inline "
                "`sql` instead of a physical table?) - excluded, no 'database.schema.table' Ossie "
                "source can be derived (see SML_OSSIE_CONVERTER_PLAN.md Edge Case #4)."
            )
            continue
        conn = connections.get(conn_id)
        if conn is None:
            raise ConversionError(f"dataset {name!r} references unknown connection_id {conn_id!r}")
        db = require(conn, "database", f"connection {conn_id!r}")
        schema = require(conn, "schema", f"connection {conn_id!r}")
        dataset_source[name] = f"{db}.{schema}.{table}"

    # A dataset that's the `from` side of some relationship is a fact table - its
    # `is_unique_key` level_attribute (if any, e.g. a degenerate dimension like a
    # date column) marks a dimension's *grain*, not a row-unique key of the fact
    # table itself, so it must not become that dataset's Ossie `primary_key`
    # (which the Snowflake Semantic View emitter turns into a literal
    # `PRIMARY KEY (...)` DDL clause - asserting uniqueness that doesn't hold).
    fact_datasets = {
        rel["from"]["dataset"]
        for rels in (model.get("relationships"), *(d.get("relationships") for d in dimensions_raw.values()))
        for rel in (rels or [])
        if isinstance(rel.get("from"), dict) and rel["from"].get("dataset")
    }

    # --- gather every (dataset, column) Ossie needs a field for, and resolve
    # each dimension's per-level join key (dataset + key_columns) for relationship
    # resolution below ---
    fields_wanted: dict[str, dict[str, bool]] = {}  # dataset -> {name_column: is_time}
    primary_key_by_dataset: dict[str, list[str]] = {}
    level_key: dict[str, dict[str, tuple[str, list[str]]]] = {}  # dim -> {level: (dataset, key_columns)}

    def _want(dataset_name: str, name_column: str, is_time: bool = False) -> None:
        bucket = fields_wanted.setdefault(dataset_name, {})
        bucket[name_column] = bucket.get(name_column, False) or is_time

    # Seed from every dataset's own declared columns first - for our own Phase 1
    # output this is exactly the original (typically partial) field list; for a
    # hand-authored repo SML requires it to be schema-exhaustive, which is fine,
    # just more fields than a hand-written Ossie model would usually declare.
    for name, raw in datasets_raw.items():
        for column in raw.get("columns") or []:
            if isinstance(column, dict) and column.get("name"):
                _want(name, column["name"])

    for dim_name, dim in dimensions_raw.items():
        dim_is_time = dim.get("type") == "time"
        level_key[dim_name] = {}
        for attr in dim.get("level_attributes") or []:
            ds = require(attr, "dataset", f"dimension {dim_name!r} level_attribute {attr.get('unique_name')!r}")
            col = require(
                attr, "name_column", f"dimension {dim_name!r} level_attribute {attr.get('unique_name')!r}"
            )
            key_columns = attr.get("key_columns") or [col]
            _want(ds, col, is_time=dim_is_time and bool(attr.get("is_unique_key")))
            level_key[dim_name][attr["unique_name"]] = (ds, key_columns)
            if attr.get("is_unique_key") and ds not in fact_datasets:
                primary_key_by_dataset[ds] = key_columns

        for hierarchy in dim.get("hierarchies") or []:
            for level in hierarchy.get("levels") or []:
                for attr in level.get("secondary_attributes") or []:
                    ds, col = attr.get("dataset"), attr.get("name_column")
                    if ds and col:
                        _want(ds, col)

    for name, raw in metrics_raw.items():
        ds, col = raw.get("dataset"), raw.get("column")
        if ds and col:
            _want(ds, col)

    # --- assemble Ossie datasets ---
    ossie_datasets: list[dict[str, Any]] = []
    for name, source in dataset_source.items():
        sml_dataset = datasets_raw[name]
        columns_by_name = {c["name"]: c for c in sml_dataset.get("columns") or [] if isinstance(c, dict)}
        wanted = fields_wanted.get(name, {})
        fields = []
        for col_name in sorted(wanted):
            column = columns_by_name.get(col_name, {})
            sql = column.get("sql") or f"{name}.{col_name}"
            field: dict[str, Any] = {
                "name": col_name,
                "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": sql}]},
            }
            datatype = sml_datatype_to_ossie(column.get("data_type"))
            if datatype:
                field["datatype"] = datatype.value
            if wanted[col_name]:
                field["dimension"] = {"is_time": True}
            fields.append(field)

        ds_dict: dict[str, Any] = {"name": name, "source": source}
        if sml_dataset.get("description"):
            ds_dict["description"] = sml_dataset["description"]
        if fields:
            ds_dict["fields"] = fields
        if name in primary_key_by_dataset:
            ds_dict["primary_key"] = primary_key_by_dataset[name]
        ossie_datasets.append(ds_dict)

    if not ossie_datasets:
        raise ConversionError("no dataset with a resolvable 'database.schema.table' source was found")

    # --- relationships: model-level (fact -> dimension) + dimension-level (snowflake/embedded) ---
    def _convert_relationship(rel: dict, context: str) -> dict[str, Any] | None:
        frm, to = rel.get("from") or {}, rel.get("to") or {}
        name = rel.get("unique_name") or f"{frm.get('dataset')}_{to.get('dimension')}"
        if to.get("row_security"):
            warnings.append(
                f"LOSSY: {context} relationship {name!r} targets row_security, which has no Ossie "
                "equivalent; excluded."
            )
            return None
        from_dataset = require(frm, "dataset", f"{context} relationship {name!r} 'from'")
        join_columns = require(frm, "join_columns", f"{context} relationship {name!r} 'from'")
        dim_name = require(to, "dimension", f"{context} relationship {name!r} 'to'")
        level_name = require(to, "level", f"{context} relationship {name!r} 'to'")
        levels = level_key.get(dim_name)
        if levels is None or level_name not in levels:
            raise ConversionError(
                f"{context} relationship {name!r} targets level {level_name!r} of dimension "
                f"{dim_name!r}, which has no matching level_attributes entry"
            )
        to_dataset, to_columns = levels[level_name]
        result: dict[str, Any] = {
            "name": name,
            "from": from_dataset,
            "to": to_dataset,
            "from_columns": join_columns,
            "to_columns": to_columns,
        }
        if rel.get("role_play"):
            # Ossie relationships have no aliasing concept - stash the SML
            # role_play template so a re-emission can reconstruct it.
            result["custom_extensions"] = [make_stash_extension({"role_play": rel["role_play"]}).model_dump()]
        return result

    ossie_relationships = [
        converted
        for rel in model.get("relationships") or []
        if (converted := _convert_relationship(rel, "model")) is not None
    ]
    for dim_name, dim in dimensions_raw.items():
        for rel in dim.get("relationships") or []:
            converted = _convert_relationship(rel, f"dimension {dim_name!r}")
            if converted is not None:
                ossie_relationships.append(converted)

    # --- metrics: plain aggregates first, so a ratio metric_calc can resolve
    # its operands' SQL regardless of file processing order ---
    ossie_metrics: list[dict[str, Any]] = []
    metric_sql_by_name: dict[str, str] = {}
    for name, raw in metrics_raw.items():
        calc_method, ds, col = raw.get("calculation_method"), raw.get("dataset"), raw.get("column")
        sql = synthesize_aggregate_sql(calc_method, ds, col) if calc_method and ds and col else None
        if sql is None:
            warnings.append(
                f"LOSSY: metric {name!r} has calculation_method {calc_method!r}, which has no single "
                "ANSI SQL aggregate equivalent; excluded."
            )
            continue
        metric_sql_by_name[name] = sql
        metric_dict: dict[str, Any] = {"name": name, "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": sql}]}}
        if raw.get("description"):
            metric_dict["description"] = raw["description"]
        ossie_metrics.append(metric_dict)

    for name, raw in metric_calcs_raw.items():
        expr = raw.get("expression") or ""
        match = _RATIO_MDX_RE.match(expr.strip())
        sql = None
        if match:
            num_sql = metric_sql_by_name.get(match.group("numerator"))
            den_sql = metric_sql_by_name.get(match.group("denominator"))
            if num_sql and den_sql:
                sql = f"{num_sql} / {den_sql}"
        metric_dict = {"name": name}
        if sql is not None:
            metric_dict["expression"] = {"dialects": [{"dialect": "ANSI_SQL", "expression": sql}]}
        else:
            metric_dict["expression"] = {"dialects": [{"dialect": "MDX", "expression": expr}]}
            warnings.append(
                f"metric_calc {name!r} MDX expression {expr!r} passed through verbatim under the MDX "
                "dialect - not executable by any Ossie SQL emitter."
            )
        if raw.get("description"):
            metric_dict["description"] = raw["description"]
        ossie_metrics.append(metric_dict)

    # --- semantic model + stash for everything with no Ossie equivalent ---
    sem_model: dict[str, Any] = {"name": model.get("unique_name"), "datasets": ossie_datasets}
    description = model.get("description") or catalog.get("description")
    if description:
        sem_model["description"] = description
    if ossie_relationships:
        sem_model["relationships"] = ossie_relationships
    if ossie_metrics:
        sem_model["metrics"] = ossie_metrics

    stash: dict[str, Any] = {}
    if dimensions_raw:
        # Full raw dimension dicts, not just the parts this converter reads -
        # hierarchy/level order, multiple hierarchies, calculation_groups, and
        # anything else, so a future Ossie -> SML re-emission of *this document*
        # could reconstruct them exactly.
        stash["dimensions"] = dimensions_raw
    if unsupported_objects:
        stash["unsupported_objects"] = unsupported_objects
    model_extra = {k: v for k, v in model.items() if k not in _HANDLED_MODEL_FIELDS}
    if model_extra:
        stash["model_extra"] = model_extra
    catalog_extra = {k: v for k, v in catalog.items() if k not in _HANDLED_CATALOG_FIELDS}
    if catalog_extra:
        stash["catalog_extra"] = catalog_extra
    if stash:
        sem_model["custom_extensions"] = [make_stash_extension(stash).model_dump()]

    document = OssieDocument.model_validate({"semantic_model": [sem_model]})
    return SmlParseResult(document=document, warnings=warnings)
