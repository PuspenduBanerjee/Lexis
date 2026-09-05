"""Ossie -> SML (Semantic Modeling Language) emitter.

SML (github.com/semanticdatalayer/SML) models a semantic layer as many small
YAML files (one per object) discriminated by `object_type`, resolved through a
global `unique_name` registry - not a single document. This emitter produces
that file set from one OssieDocument.

v1 is the "documented supported subset" (see SML_OSSIE_CONVERTER_PLAN.md at the
repo root): datasets, a synthesized single-level dimension per relationship
target, relationships, and metrics that decompose into a plain
`AGG(dataset.column)` shape. A metric that is a ratio of two such aggregates
(`AGG(a.b) / AGG(c.d)`, optionally with a `NULLIF(..., 0)` divide-by-zero guard
on the denominator) becomes an SML `metric_calc` with a synthesized MDX division
expression - the exact shape SML's own docs use for ratio metrics - referencing
two plain `metric` objects (reusing an existing one with the same aggregate
shape when available, e.g. a `total_sales` metric doubling as a ratio's
numerator, rather than duplicating it). A metric that doesn't decompose either
way is preserved verbatim (never faked as arbitrary MDX) under a small
`x_lexis_unconverted_metrics` escape hatch on the emitted `model.yml` - SML
itself has no vendor-extension slot for an object it can't represent at all -
so a later `parse_sml_repo()` call restores it exactly rather than losing it
silently, mirroring the "no silent loss" convention Ossie's other bidirectional
converters use (see `SML_OSSIE_CONVERTER_PLAN.md`'s Phase 3 section).

If `document` was itself produced by `parse_sml_repo()`, this emitter is
stash-aware: a dimension whose full original shape (hierarchies, levels,
calculation_groups, ...) was stashed under `custom_extensions` on the way in is
re-emitted verbatim instead of re-flattened into a fresh single-level
synthesis, so an SML -> Ossie -> SML round trip doesn't lose hierarchy
structure it never needed to lose.
"""

from dataclasses import dataclass
from typing import Any

import yaml

from lexis._vendor.ossie import OssieDataset, OssieDialect, OssieDocument
from lexis.resolved_model import MissingExpressionError, ResolvedModel
from lexis.sml._common import (
    OSSIE_TO_SML_DATATYPE,
    decompose_ratio_aggregate,
    decompose_simple_aggregate,
    read_stash,
)
from lexis.sml.models import (
    SmlCatalog,
    SmlConnection,
    SmlDataset,
    SmlDatasetColumn,
    SmlDimension,
    SmlHierarchy,
    SmlLevel,
    SmlLevelAttribute,
    SmlMetric,
    SmlMetricCalc,
    SmlModel,
    SmlModelMetricRef,
    SmlModelRelationship,
    SmlRelationshipEnd,
)


@dataclass(frozen=True)
class SmlEmitResult:
    files: dict[str, str]
    warnings: list[str]


def _dump(obj) -> str:
    data = obj.model_dump(by_alias=True, exclude_none=True, mode="json")
    return yaml.dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)


def _split_source(dataset: OssieDataset, warnings: list[str]) -> tuple[str, str, str] | None:
    """Split `database.schema.table`; warn and return None if source isn't 3-part
    (mirrors dbt_ossie.py's `_source_shape_warnings` check on the same convention)."""
    parts = dataset.source.split(".")
    if len(parts) != 3 or not all(parts):
        warnings.append(
            f"LOSSY: dataset {dataset.name!r} source {dataset.source!r} is not "
            "'database.schema.table' - SML requires a connection + table name; "
            "this dataset was excluded from the SML output."
        )
        return None
    return parts[0], parts[1], parts[2]


def _emit_dimension(
    dataset: OssieDataset, warnings: list[str]
) -> tuple[dict[str, str], str | None]:
    """Synthesize a single-level SML dimension for `dataset`.

    v1 flattens every Ossie field into one level's key/secondary attributes
    rather than attempting to infer a natural multi-level hierarchy - Ossie has
    no data (level order, grouping) that would justify one. Hand-edit the
    emitted SML if a richer hierarchy is wanted. See SML_OSSIE_CONVERTER_PLAN.md.
    """
    dim_name = f"{dataset.name} Dimension"
    fields = dataset.fields or []
    if not fields:
        warnings.append(f"LOSSY: dataset {dataset.name!r} has no fields; dimension skipped.")
        return {}, None

    key_field = dataset.primary_key[0] if dataset.primary_key else fields[0].name
    is_time = any(f.is_time_dimension() for f in fields)

    # Per SML's dimension.md spec, dimension-level `level_attributes` holds only
    # the one joinable key attribute per level ("Only level attributes can be
    # used to define relationships between datasets and other dimensions") -
    # our single synthesized level has exactly one. Every other field is a
    # non-joinable secondary attribute, inlined directly under the level rather
    # than duplicated at the dimension level.
    key_attribute = SmlLevelAttribute(
        unique_name=dim_name,
        dataset=dataset.name,
        name_column=key_field,
        key_columns=[key_field],
        is_unique_key=True,
    )
    secondary_attributes = [
        SmlLevelAttribute(
            unique_name=f"{dataset.name} {f.name}",
            dataset=dataset.name,
            name_column=f.name,
            key_columns=[f.name],
        )
        for f in fields
        if f.name != key_field
    ]

    hierarchy = SmlHierarchy(
        unique_name=dim_name,
        levels=[SmlLevel(unique_name=dim_name, secondary_attributes=secondary_attributes or None)],
    )
    dimension = SmlDimension(
        unique_name=dim_name,
        type="time" if is_time else "standard",
        hierarchies=[hierarchy],
        level_attributes=[key_attribute],
    )
    return {f"dimensions/{dim_name}.yml": _dump(dimension)}, dim_name


def _dump_raw(data: dict) -> str:
    return yaml.dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)


def _leaf_level_of(raw_dimension: dict) -> str:
    """The dimension's grain-key level unique_name - what a relationship's
    `to.level` must reference. Falls back to the dimension's own unique_name,
    matching `_emit_dimension`'s own single-level synthesis convention, if no
    `level_attributes` entry is marked `is_unique_key`."""
    for attr in raw_dimension.get("level_attributes") or []:
        if attr.get("is_unique_key"):
            return attr["unique_name"]
    return raw_dimension.get("unique_name")


def _stashed_dimensions_by_dataset(stashed_dimensions: dict[str, dict]) -> dict[str, str]:
    """Reverse-index the stash: physical dataset name -> the (first) stashed
    dimension unique_name whose `level_attributes` names it. A snowflaked
    dimension spanning multiple datasets is looked up by whichever of its
    datasets a relationship or degenerate-dimension pass asks about."""
    by_dataset: dict[str, str] = {}
    for dim_name, raw_dim in stashed_dimensions.items():
        for attr in raw_dim.get("level_attributes") or []:
            ds = attr.get("dataset")
            if ds:
                by_dataset.setdefault(ds, dim_name)
    return by_dataset


def _metric_ref_for_aggregate(
    aggregate: tuple[str, str, str],
    aggregate_index: dict[tuple[str, str, str], str],
    files: dict[str, str],
    metric_refs: list[SmlModelMetricRef],
) -> str:
    """Return the unique_name of an SML metric matching `aggregate`
    (calculation_method, dataset, column) - reusing an existing metric with that
    exact shape (from `aggregate_index`, populated from every metric that already
    decomposes to a plain aggregate) if one exists, else synthesizing and emitting
    a new helper metric for it. Used to build a ratio metric_calc's MDX operands."""
    if aggregate in aggregate_index:
        return aggregate_index[aggregate]
    calc_method, ds_name, column = aggregate
    name = f"{ds_name}.{column} {calc_method}"
    files[f"metrics/{name}.yml"] = _dump(
        SmlMetric(unique_name=name, label=name, calculation_method=calc_method, dataset=ds_name, column=column)
    )
    metric_refs.append(SmlModelMetricRef(unique_name=name))
    aggregate_index[aggregate] = name
    return name


def emit_sml_files(document: OssieDocument) -> SmlEmitResult:
    """Render `document`'s first semantic model as an SML file set."""
    semantic_model = document.semantic_model[0]
    model = ResolvedModel.build(semantic_model)
    warnings: list[str] = []
    files: dict[str, str] = {}

    stash = read_stash(semantic_model)
    stashed_dimensions: dict[str, dict] = stash.get("dimensions", {})
    stashed_dim_by_dataset = _stashed_dimensions_by_dataset(stashed_dimensions)
    emitted_dimension_names: set[str] = set()

    # --- connections: one per unique (database, schema) pair ---
    dataset_parts: dict[str, tuple[str, str, str]] = {}
    connection_names: dict[tuple[str, str], str] = {}
    for dataset in semantic_model.datasets:
        parts = _split_source(dataset, warnings)
        if parts is None:
            continue
        dataset_parts[dataset.name] = parts
        db, schema, _table = parts
        key = (db, schema)
        if key not in connection_names:
            conn_name = f"Connection - {db}.{schema}"
            connection_names[key] = conn_name
            conn = SmlConnection(unique_name=conn_name, database=db, schema_name=schema)
            files[f"connections/{conn_name}.yml"] = _dump(conn)

    # --- datasets (+ a dimension for every relationship target: re-emitted
    # verbatim from the stash if this dataset was originally parsed from one,
    # else freshly synthesized as a single flat level) ---
    dimension_targets = {rel.to for rel in model.relationships}
    dimension_key: dict[str, tuple[str, str]] = {}  # dataset -> (dimension unique_name, leaf level unique_name)
    for dataset in semantic_model.datasets:
        if dataset.name not in dataset_parts:
            continue
        db, schema, table = dataset_parts[dataset.name]

        columns = []
        for f in dataset.fields or []:
            try:
                sql = model.resolve_expression(f.expression, OssieDialect.ANSI_SQL)
            except MissingExpressionError:
                warnings.append(
                    f"LOSSY: field {dataset.name}.{f.name!r} has no ANSI_SQL expression; "
                    "column excluded from the SML dataset."
                )
                continue
            data_type = OSSIE_TO_SML_DATATYPE.get(f.datatype) if f.datatype else None
            columns.append(
                SmlDatasetColumn(name=f.name, data_type=data_type, sql=None if sql == f.name else sql)
            )

        sml_dataset = SmlDataset(
            unique_name=dataset.name,
            label=dataset.name,
            description=dataset.description,
            connection_id=connection_names[(db, schema)],
            table=table,
            columns=columns,
        )
        files[f"datasets/{dataset.name}.yml"] = _dump(sml_dataset)

        if dataset.name in dimension_targets:
            stashed_name = stashed_dim_by_dataset.get(dataset.name)
            if stashed_name:
                raw_dim = stashed_dimensions[stashed_name]
                if stashed_name not in emitted_dimension_names:
                    files[f"dimensions/{stashed_name}.yml"] = _dump_raw(raw_dim)
                    emitted_dimension_names.add(stashed_name)
                dimension_key[dataset.name] = (stashed_name, _leaf_level_of(raw_dim))
            else:
                dim_files, dim_name = _emit_dimension(dataset, warnings)
                files.update(dim_files)
                if dim_name:
                    dimension_key[dataset.name] = (dim_name, dim_name)

    # A degenerate/shared-degenerate dimension (keyed on a fact dataset's own
    # column) has no relationship pointing at it - `dimension_targets` above
    # never catches it - so re-emit any stashed dimension not already handled,
    # as long as its backing dataset(s) are still part of this document.
    for dim_name, raw_dim in stashed_dimensions.items():
        if dim_name in emitted_dimension_names:
            continue
        backing_datasets = {a.get("dataset") for a in raw_dim.get("level_attributes") or []}
        if backing_datasets & dataset_parts.keys():
            files[f"dimensions/{dim_name}.yml"] = _dump_raw(raw_dim)
            emitted_dimension_names.add(dim_name)

    # --- metrics ---
    # First pass: resolve every metric's expression and record which ones decompose
    # to a plain aggregate, so a ratio metric processed below can reuse one as an
    # operand (e.g. `total_sales`) regardless of the two metrics' declaration order.
    resolved: list[tuple] = []
    aggregate_index: dict[tuple[str, str, str], str] = {}
    unconverted_metrics: list[dict[str, Any]] = []
    for metric in semantic_model.metrics or []:
        try:
            expr = model.resolve_expression(metric.expression, OssieDialect.ANSI_SQL)
        except MissingExpressionError:
            warnings.append(
                f"LOSSY: metric {metric.name!r} has no ANSI_SQL expression; preserved verbatim "
                "(not a queryable SML metric/metric_calc, but round-trips back to Ossie)."
            )
            unconverted_metrics.append(metric.model_dump(exclude_none=True, mode="json"))
            resolved.append((metric, None))
            continue
        resolved.append((metric, expr))
        decomposed = decompose_simple_aggregate(expr)
        if decomposed is not None and decomposed not in aggregate_index:
            # First declaration wins if two metrics share the same aggregate shape,
            # so which one a later ratio metric_calc references is deterministic
            # and follows document order rather than depending on dict overwrite order.
            aggregate_index[decomposed] = metric.name

    metric_refs = []
    for metric, expr in resolved:
        if expr is None:
            continue

        decomposed = decompose_simple_aggregate(expr)
        if decomposed is not None:
            calc_method, ds_name, column = decomposed
            sml_metric = SmlMetric(
                unique_name=metric.name,
                label=metric.name,
                description=metric.description,
                calculation_method=calc_method,
                dataset=ds_name,
                column=column,
            )
            files[f"metrics/{metric.name}.yml"] = _dump(sml_metric)
            metric_refs.append(SmlModelMetricRef(unique_name=metric.name))
            continue

        ratio = decompose_ratio_aggregate(expr)
        if ratio is not None:
            numerator_ref = _metric_ref_for_aggregate(ratio.numerator, aggregate_index, files, metric_refs)
            denominator_ref = _metric_ref_for_aggregate(ratio.denominator, aggregate_index, files, metric_refs)
            metric_calc = SmlMetricCalc(
                unique_name=metric.name,
                label=metric.name,
                description=metric.description,
                expression=f"[Measures].[{numerator_ref}]/[Measures].[{denominator_ref}]",
            )
            files[f"metrics/{metric.name}.yml"] = _dump(metric_calc)
            metric_refs.append(SmlModelMetricRef(unique_name=metric.name))
            if ratio.denominator_nullif_guard_dropped:
                warnings.append(
                    f"metric {metric.name!r}: the SQL denominator's NULLIF(..., 0) divide-by-zero "
                    "guard has no MDX equivalent (MDX division already returns blank/error on "
                    "divide-by-zero) and was dropped from the emitted metric_calc; behavior at a "
                    "zero denominator may differ."
                )
            continue

        warnings.append(
            f"LOSSY: metric {metric.name!r} expression {expr!r} is not a simple AGG(dataset.column) "
            "aggregate or a ratio of two such aggregates - preserved verbatim (not a queryable SML "
            "metric/metric_calc, but round-trips back to Ossie) rather than faked as arbitrary MDX."
        )
        unconverted_metrics.append(metric.model_dump(exclude_none=True, mode="json"))

    # --- model-level relationships (fact -> dimension) ---
    relationships = []
    for rel in model.relationships:
        target = dimension_key.get(rel.to)
        if target is None:
            warnings.append(
                f"LOSSY: relationship {rel.name!r} targets dataset {rel.to!r}, which has "
                "no synthesized dimension; relationship excluded from SML output."
            )
            continue
        dim_name, leaf_level = target
        relationships.append(
            SmlModelRelationship(
                unique_name=rel.name,
                from_end=SmlRelationshipEnd(dataset=rel.from_dataset, join_columns=rel.from_columns),
                to=SmlRelationshipEnd(dimension=dim_name, level=leaf_level),
            )
        )

    sml_model_data: dict[str, Any] = dict(
        unique_name=semantic_model.name,
        label=semantic_model.name,
        description=semantic_model.description,
        relationships=relationships,
        metrics=metric_refs,
    )
    if unconverted_metrics:
        # No SML object has a vendor-extension slot to stash an unconvertible
        # metric on, unlike Ossie's own `custom_extensions` - this small,
        # clearly-namespaced escape hatch on `model.yml` is this converter's
        # own, restored by `parse.py`'s matching `x_lexis_unconverted_metrics` read.
        sml_model_data["x_lexis_unconverted_metrics"] = unconverted_metrics
    sml_model = SmlModel(**sml_model_data)
    files[f"models/{semantic_model.name}.yml"] = _dump(sml_model)

    # --- catalog ---
    catalog = SmlCatalog(
        unique_name=semantic_model.name,
        label=semantic_model.name,
        description=semantic_model.description,
    )
    files["catalog.yml"] = _dump(catalog)

    return SmlEmitResult(files=files, warnings=warnings)
