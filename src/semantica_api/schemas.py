"""Pydantic request/response schemas for the API.

Deliberately separate from the vendored `semantica._vendor.osi` pydantic models —
the HTTP contract shouldn't be coupled to (and broken by) internal vendored-library
shape changes. `to_*_out` helpers below map OSI objects into these schemas.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from semantica._vendor.osi import OSIDataset, OSIDialect, OSIMetric, OSIRelationship
from semantica.resolved_model import MissingExpressionError, ResolvedModel
from semantica_api.models import SemanticModelRecord

TARGET = Literal[
    "duckdb", "postgres", "bigquery", "databricks", "snowflake", "cube", "dbt", "mcp"
]

TIME_GRAIN = Literal["year", "quarter", "month", "day"]


class UserOut(BaseModel):
    id: int
    username: str
    role: str


class FieldOut(BaseModel):
    name: str
    description: str | None = None
    expression: str | None = None  # ANSI_SQL text, best-effort (None if unavailable)
    is_time: bool = False  # from OSI's `dimension.is_time` - candidate for time-series grain grouping


class DatasetOut(BaseModel):
    name: str
    source: str
    fields: list[FieldOut]


class RelationshipOut(BaseModel):
    name: str
    from_dataset: str
    to: str
    from_columns: list[str]
    to_columns: list[str]


class MetricOut(BaseModel):
    name: str
    description: str | None = None
    expression: str | None = None  # ANSI_SQL text, best-effort (None if unavailable)
    referenced_datasets: list[str] = []


class ModelSummaryOut(BaseModel):
    id: int
    name: str
    owner_id: int
    owner_username: str
    dataset_count: int
    metric_count: int
    created_at: datetime
    updated_at: datetime


class ModelDetailOut(ModelSummaryOut):
    raw_yaml: str
    datasets: list[DatasetOut]
    relationships: list[RelationshipOut]
    metrics: list[MetricOut]


class CreateModelIn(BaseModel):
    name: str | None = None
    yaml_text: str


class UpdateModelIn(BaseModel):
    yaml_text: str


class TranspileIn(BaseModel):
    target: TARGET
    metric: str | None = None
    group_by: list[str] | None = None


class TranspileOut(BaseModel):
    content: str
    warnings: list[str]


class RunDuckDbOut(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    sql: str


class GraphFieldIn(BaseModel):
    name: str
    expression: str  # ANSI_SQL text
    description: str | None = None


class GraphDatasetIn(BaseModel):
    name: str
    source: str
    fields: list[GraphFieldIn] = []


class GraphRelationshipIn(BaseModel):
    name: str
    from_dataset: str
    to: str
    from_columns: list[str]
    to_columns: list[str]


class GraphEditIn(BaseModel):
    """Structured graph-canvas state for a model's datasets/relationships. Applied by
    merging onto the existing parsed OSIDocument (see graph_edit.py) so attributes the
    canvas has no control for (ai_context, custom_extensions, non-ANSI_SQL dialect
    expressions, primary_key/unique_keys, metrics) are preserved untouched."""

    datasets: list[GraphDatasetIn]
    relationships: list[GraphRelationshipIn] = []


def _expression_text(model: ResolvedModel, expressed) -> str | None:
    """Best-effort ANSI_SQL text for anything with an `.expression: OSIExpression`
    attribute (OSIField or OSIMetric)."""
    try:
        return model.resolve_expression(expressed.expression, OSIDialect.ANSI_SQL)
    except MissingExpressionError:
        return None


def to_dataset_out(dataset: OSIDataset, model: ResolvedModel) -> DatasetOut:
    return DatasetOut(
        name=dataset.name,
        source=dataset.source,
        fields=[
            FieldOut(
                name=f.name,
                description=f.description,
                expression=_expression_text(model, f),
                is_time=bool(f.dimension and f.dimension.is_time),
            )
            for f in dataset.fields or []
        ],
    )


def to_relationship_out(rel: OSIRelationship) -> RelationshipOut:
    return RelationshipOut(
        name=rel.name,
        from_dataset=rel.from_dataset,
        to=rel.to,
        from_columns=rel.from_columns,
        to_columns=rel.to_columns,
    )


def to_metric_out(metric: OSIMetric, model: ResolvedModel) -> MetricOut:
    expression = _expression_text(model, metric)
    return MetricOut(
        name=metric.name,
        description=metric.description,
        expression=expression,
        referenced_datasets=model.referenced_datasets(expression) if expression else [],
    )


def to_summary_out(record: SemanticModelRecord, model: ResolvedModel) -> ModelSummaryOut:
    return ModelSummaryOut(
        id=record.id,
        name=record.name,
        owner_id=record.owner_id,
        owner_username=record.owner.username,
        dataset_count=len(model.datasets),
        metric_count=len(model.metrics),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_detail_out(record: SemanticModelRecord, model: ResolvedModel) -> ModelDetailOut:
    summary = to_summary_out(record, model)
    return ModelDetailOut(
        **summary.model_dump(),
        raw_yaml=record.raw_yaml,
        datasets=[to_dataset_out(d, model) for d in model.datasets.values()],
        relationships=[to_relationship_out(r) for r in model.relationships],
        metrics=[to_metric_out(m, model) for m in model.metrics.values()],
    )
