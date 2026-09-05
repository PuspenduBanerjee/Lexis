"""Hand-written pydantic models for the SML (Semantic Modeling Language) object
subset this converter supports.

SML (github.com/semanticdatalayer/SML) has no public JSON Schema and no
open-source reference parser/validator - AtScale's `sml-sdk`/`sml-cli` tooling
is closed-source. These models are derived from the spec's Markdown
documentation, not validated against any canonical schema (see
SML_OSSIE_CONVERTER_PLAN.md, Edge Case #5). `extra="allow"` on every model so a
real-world SML file with fields beyond this documented subset still round-trips
through `model_validate`/`model_dump` rather than being rejected or silently
truncated once Phase 2's parser exists.

Only the object types/fields the v1 "documented supported subset" needs are
modeled here (catalog, connection, dataset, dimension, metric, metric_calc,
model, and the relationship shapes). Everything else SML has (row_security,
perspectives, drillthroughs, composite_model, packages, ...) has no Ossie
equivalent and is out of scope for this converter entirely - not just for
these models.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SmlDialectSql(BaseModel):
    model_config = ConfigDict(extra="allow")

    dialect: str
    sql: str


class SmlDatasetColumn(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    data_type: Optional[str] = None
    sql: Optional[str] = None
    dialects: Optional[list[SmlDialectSql]] = None


class SmlConnection(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    unique_name: str
    object_type: Literal["connection"] = "connection"
    label: Optional[str] = None
    as_connection: Optional[str] = None
    database: Optional[str] = None
    schema_name: Optional[str] = Field(None, alias="schema")


class SmlDataset(BaseModel):
    model_config = ConfigDict(extra="allow")

    unique_name: str
    object_type: Literal["dataset"] = "dataset"
    label: Optional[str] = None
    description: Optional[str] = None
    connection_id: Optional[str] = None
    table: Optional[str] = None
    sql: Optional[str] = None
    columns: list[SmlDatasetColumn] = []


class SmlLevelAttribute(BaseModel):
    model_config = ConfigDict(extra="allow")

    unique_name: str
    dataset: str
    name_column: str
    key_columns: list[str]
    is_unique_key: Optional[bool] = None


class SmlLevel(BaseModel):
    model_config = ConfigDict(extra="allow")

    unique_name: str
    secondary_attributes: Optional[list[str]] = None


class SmlHierarchy(BaseModel):
    model_config = ConfigDict(extra="allow")

    unique_name: str
    label: Optional[str] = None
    levels: list[SmlLevel] = []


class SmlDimension(BaseModel):
    model_config = ConfigDict(extra="allow")

    unique_name: str
    object_type: Literal["dimension"] = "dimension"
    label: Optional[str] = None
    type: Literal["standard", "time"] = "standard"
    hierarchies: list[SmlHierarchy] = []
    level_attributes: list[SmlLevelAttribute] = []


class SmlMetric(BaseModel):
    model_config = ConfigDict(extra="allow")

    unique_name: str
    object_type: Literal["metric"] = "metric"
    label: Optional[str] = None
    description: Optional[str] = None
    calculation_method: str
    dataset: str
    column: str


class SmlMetricCalc(BaseModel):
    model_config = ConfigDict(extra="allow")

    unique_name: str
    object_type: Literal["metric_calc"] = "metric_calc"
    label: Optional[str] = None
    description: Optional[str] = None
    expression: str


class SmlRelationshipEnd(BaseModel):
    model_config = ConfigDict(extra="allow")

    dataset: Optional[str] = None
    join_columns: Optional[list[str]] = None
    dimension: Optional[str] = None
    level: Optional[str] = None


class SmlModelRelationship(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    unique_name: str
    from_end: SmlRelationshipEnd = Field(..., alias="from")
    to: SmlRelationshipEnd
    role_play: Optional[str] = None


class SmlModelMetricRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    unique_name: str


class SmlModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    unique_name: str
    object_type: Literal["model"] = "model"
    label: Optional[str] = None
    description: Optional[str] = None
    relationships: list[SmlModelRelationship] = []
    metrics: list[SmlModelMetricRef] = []


class SmlCatalog(BaseModel):
    model_config = ConfigDict(extra="allow")

    unique_name: str
    object_type: Literal["catalog"] = "catalog"
    label: Optional[str] = None
    description: Optional[str] = None
