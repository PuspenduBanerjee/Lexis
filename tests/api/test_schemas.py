"""Unit tests for the to_*_out mapping helpers in semantica_api.schemas.

Pure-function tests (no HTTP/DB involved) - lives under tests/api/ alongside the
rest of the semantica_api test suite rather than tests/, per the existing split
between core-library tests and semantica_api tests.
"""

from semantica._vendor.ossie import (
    OssieDataset,
    OssieDataType,
    OssieDialect,
    OssieDialectExpression,
    OssieDimension,
    OssieExpression,
    OssieField,
    OssieMetric,
    OssieSemanticModel,
)
from semantica.resolved_model import ResolvedModel
from semantica_api.schemas import to_dataset_out, to_metric_out


def _ansi_expr(text: str) -> OssieExpression:
    return OssieExpression(dialects=[OssieDialectExpression(dialect=OssieDialect.ANSI_SQL, expression=text)])


def _model(fields: list[OssieField]) -> ResolvedModel:
    dataset = OssieDataset(name="orders", source="db.schema.orders", fields=fields)
    semantic_model = OssieSemanticModel(name="m", datasets=[dataset])
    return ResolvedModel.build(semantic_model)


def test_to_dataset_out_passes_through_explicit_is_time_and_datatype():
    field = OssieField(
        name="order_date",
        expression=_ansi_expr("order_date"),
        dimension=OssieDimension(is_time=True),
        datatype=OssieDataType.DATE,
    )
    out = to_dataset_out(_model([field]).datasets["orders"], _model([field]))
    field_out = out.fields[0]
    assert field_out.is_time is True
    assert field_out.datatype == "Date"


def test_to_dataset_out_derives_is_time_from_datatype_when_unset():
    # No explicit dimension.is_time, but a temporal datatype - is_time_dimension()
    # should fall back to the datatype-based default.
    field = OssieField(
        name="created_at",
        expression=_ansi_expr("created_at"),
        dimension=OssieDimension(),  # is_time left unset (None)
        datatype=OssieDataType.DATE_TIME,
    )
    model = _model([field])
    out = to_dataset_out(model.datasets["orders"], model)
    assert out.fields[0].is_time is True


def test_to_dataset_out_temporal_datatype_without_dimension_block_is_not_time():
    # is_time_dimension() requires a dimension block to be present at all -
    # a temporal datatype alone (no dimension metadata) doesn't make it a dimension.
    field = OssieField(
        name="created_at",
        expression=_ansi_expr("created_at"),
        datatype=OssieDataType.DATE_TIME,
    )
    model = _model([field])
    out = to_dataset_out(model.datasets["orders"], model)
    assert out.fields[0].is_time is False


def test_to_dataset_out_datatype_none_when_not_declared():
    field = OssieField(name="notes", expression=_ansi_expr("notes"))
    model = _model([field])
    out = to_dataset_out(model.datasets["orders"], model)
    assert out.fields[0].datatype is None


def test_to_metric_out_passes_through_datatype():
    metric = OssieMetric(name="total", expression=_ansi_expr("SUM(orders.amount)"), datatype=OssieDataType.DECIMAL)
    semantic_model = OssieSemanticModel(
        name="m",
        datasets=[OssieDataset(name="orders", source="db.schema.orders")],
        metrics=[metric],
    )
    model = ResolvedModel.build(semantic_model)
    out = to_metric_out(model.metrics["total"], model)
    assert out.datatype == "Decimal"


def test_to_metric_out_datatype_none_when_not_declared():
    metric = OssieMetric(name="total", expression=_ansi_expr("SUM(orders.amount)"))
    semantic_model = OssieSemanticModel(
        name="m",
        datasets=[OssieDataset(name="orders", source="db.schema.orders")],
        metrics=[metric],
    )
    model = ResolvedModel.build(semantic_model)
    out = to_metric_out(model.metrics["total"], model)
    assert out.datatype is None
