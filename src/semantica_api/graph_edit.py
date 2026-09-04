"""Apply structured graph-canvas edits onto an existing parsed OssieDocument.

The canvas only exposes a subset of what Ossie datasets/fields/relationships/metrics
can carry (name, source, ANSI_SQL expression, description). Anything else an existing
entity has - ai_context, custom_extensions, primary_key/unique_keys, non-ANSI_SQL
dialect expressions - must survive a save untouched. So this merges the incoming
structured edit onto the existing parsed pydantic objects (matching by name) rather
than rebuilding OssieDataset/OssieField/OssieRelationship/OssieMetric from scratch, and
re-serializes via the existing OssieDocument.to_ossie_yaml() - no separate YAML
generation logic.
"""

from semantica._vendor.ossie import (
    OssieDataset,
    OssieDialect,
    OssieDialectExpression,
    OssieDocument,
    OssieExpression,
    OssieField,
    OssieMetric,
    OssieRelationship,
)
from semantica_api.schemas import (
    GraphDatasetIn,
    GraphEditIn,
    GraphFieldIn,
    GraphMetricIn,
    GraphRelationshipIn,
)


def _merge_field(existing: OssieField | None, field_in: GraphFieldIn) -> OssieField:
    other_dialects = (
        [d for d in existing.expression.dialects if d.dialect != OssieDialect.ANSI_SQL] if existing else []
    )
    expression = OssieExpression(
        dialects=[OssieDialectExpression(dialect=OssieDialect.ANSI_SQL, expression=field_in.expression), *other_dialects]
    )
    if existing is not None:
        return existing.model_copy(update={"expression": expression, "description": field_in.description})
    return OssieField(name=field_in.name, expression=expression, description=field_in.description)


def _merge_dataset(existing: OssieDataset | None, dataset_in: GraphDatasetIn) -> OssieDataset:
    existing_fields = {f.name: f for f in (existing.fields or [])} if existing else {}
    fields = [_merge_field(existing_fields.get(f.name), f) for f in dataset_in.fields]
    if existing is not None:
        return existing.model_copy(update={"source": dataset_in.source, "fields": fields})
    return OssieDataset(name=dataset_in.name, source=dataset_in.source, fields=fields)


def _merge_metric(existing: OssieMetric | None, metric_in: GraphMetricIn) -> OssieMetric:
    other_dialects = (
        [d for d in existing.expression.dialects if d.dialect != OssieDialect.ANSI_SQL] if existing else []
    )
    expression = OssieExpression(
        dialects=[OssieDialectExpression(dialect=OssieDialect.ANSI_SQL, expression=metric_in.expression), *other_dialects]
    )
    if existing is not None:
        return existing.model_copy(update={"expression": expression, "description": metric_in.description})
    return OssieMetric(name=metric_in.name, expression=expression, description=metric_in.description)


def _merge_relationship(existing: OssieRelationship | None, rel_in: GraphRelationshipIn) -> OssieRelationship:
    updates = {
        "from_dataset": rel_in.from_dataset,
        "to": rel_in.to,
        "from_columns": rel_in.from_columns,
        "to_columns": rel_in.to_columns,
    }
    if existing is not None:
        return existing.model_copy(update=updates)
    return OssieRelationship(name=rel_in.name, **updates)


def _check_unique(names: list[str], kind: str) -> None:
    seen = set()
    for name in names:
        if name in seen:
            raise ValueError(f"duplicate {kind} name in graph edit: {name!r}")
        seen.add(name)


def apply_graph_edit(document: OssieDocument, edit: GraphEditIn) -> OssieDocument:
    """Return a new OssieDocument with datasets/relationships/metrics replaced by `edit`."""
    semantic_model = document.semantic_model[0]

    _check_unique([d.name for d in edit.datasets], "dataset")
    for dataset_in in edit.datasets:
        _check_unique([f.name for f in dataset_in.fields], f"field (in dataset {dataset_in.name!r})")
    _check_unique([r.name for r in edit.relationships], "relationship")
    _check_unique([m.name for m in edit.metrics], "metric")

    dataset_names = {d.name for d in edit.datasets}
    for rel in edit.relationships:
        if rel.from_dataset not in dataset_names:
            raise ValueError(f"relationship {rel.name!r} references unknown dataset {rel.from_dataset!r}")
        if rel.to not in dataset_names:
            raise ValueError(f"relationship {rel.name!r} references unknown dataset {rel.to!r}")

    existing_datasets = {d.name: d for d in semantic_model.datasets}
    new_datasets = [_merge_dataset(existing_datasets.get(d.name), d) for d in edit.datasets]

    existing_relationships = {r.name: r for r in (semantic_model.relationships or [])}
    new_relationships = [_merge_relationship(existing_relationships.get(r.name), r) for r in edit.relationships]

    existing_metrics = {m.name: m for m in (semantic_model.metrics or [])}
    new_metrics = [_merge_metric(existing_metrics.get(m.name), m) for m in edit.metrics]

    updated_model = semantic_model.model_copy(
        update={"datasets": new_datasets, "relationships": new_relationships, "metrics": new_metrics}
    )
    return document.model_copy(update={"semantic_model": [updated_model]})
