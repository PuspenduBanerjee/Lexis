"""Live DuckDB execution of a model's metric+group-by, against an upload or the demo dataset."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

from semantica._vendor.osi import OSIDialect
from semantica.parser import parse_osi_yaml
from semantica.resolved_model import ResolvedModel
from semantica_api.deps import get_visible_model
from semantica_api.duckdb_runtime import (
    build_tpcds_demo_connection,
    catalog_name_for_upload,
    check_demo_compatible,
    open_uploaded_database,
    run_metric_query,
    run_timeseries_query,
    saved_upload,
)
from semantica_api.models import SemanticModelRecord
from semantica_api.schemas import RunDuckDbOut

router = APIRouter(prefix="/api/models", tags=["duckdb"])


@router.post("/{model_id}/run", response_model=RunDuckDbOut)
def run_duckdb(
    mode: Literal["upload", "demo"] = Form(...),
    metric: str = Form(...),
    group_by_json: str = Form("[]"),
    file: UploadFile | None = None,
    record: SemanticModelRecord = Depends(get_visible_model),
) -> RunDuckDbOut:
    document = parse_osi_yaml(record.raw_yaml)
    model = ResolvedModel.build(document.semantic_model[0])
    group_by: list[str] = json.loads(group_by_json)

    metric_obj = model.metrics.get(metric)
    if metric_obj is None:
        raise HTTPException(status_code=422, detail=f"unknown metric {metric!r}")
    metric_expr = model.resolve_expression(metric_obj.expression, OSIDialect.ANSI_SQL)
    referenced = set(model.referenced_datasets(metric_expr))
    referenced |= {ref.split(".", 1)[0] for ref in group_by}

    if mode == "demo":
        check_demo_compatible(model, referenced)
        con = build_tpcds_demo_connection()
        try:
            result = run_metric_query(con, model, metric, group_by or None)
        finally:
            con.close()
    else:
        if file is None:
            raise HTTPException(status_code=400, detail="file is required when mode='upload'")
        catalog_name = catalog_name_for_upload(model, referenced)
        with saved_upload(file) as path, open_uploaded_database(path, catalog_name) as con:
            result = run_metric_query(con, model, metric, group_by or None)

    return RunDuckDbOut(**result)


@router.post("/{model_id}/run/timeseries", response_model=RunDuckDbOut)
def run_duckdb_timeseries(
    mode: Literal["upload", "demo"] = Form(...),
    metric: str = Form(...),
    time_dataset: str = Form(...),
    time_field: str = Form(...),
    grain: str = Form(...),
    filter_grain: str | None = Form(None),
    filter_value: str | None = Form(None),
    file: UploadFile | None = None,
    record: SemanticModelRecord = Depends(get_visible_model),
) -> RunDuckDbOut:
    """Group a metric by DATE_TRUNC(grain, time_field) - the query behind the Design
    tab's and Run DuckDB tab's drill-down/roll-up time-series view. `filter_grain`/
    `filter_value` restrict to one coarser period, for drilling into it."""
    document = parse_osi_yaml(record.raw_yaml)
    model = ResolvedModel.build(document.semantic_model[0])

    metric_obj = model.metrics.get(metric)
    if metric_obj is None:
        raise HTTPException(status_code=422, detail=f"unknown metric {metric!r}")
    if time_dataset not in model.datasets:
        raise HTTPException(status_code=422, detail=f"unknown dataset {time_dataset!r}")

    metric_expr = model.resolve_expression(metric_obj.expression, OSIDialect.ANSI_SQL)
    referenced = set(model.referenced_datasets(metric_expr)) | {time_dataset}

    if mode == "demo":
        check_demo_compatible(model, referenced)
        con = build_tpcds_demo_connection()
        try:
            result = run_timeseries_query(
                con, model, metric, time_dataset, time_field, grain, filter_grain, filter_value
            )
        finally:
            con.close()
    else:
        if file is None:
            raise HTTPException(status_code=400, detail="file is required when mode='upload'")
        catalog_name = catalog_name_for_upload(model, referenced)
        with saved_upload(file) as path, open_uploaded_database(path, catalog_name) as con:
            result = run_timeseries_query(
                con, model, metric, time_dataset, time_field, grain, filter_grain, filter_value
            )

    return RunDuckDbOut(**result)
