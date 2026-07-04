"""Live query execution of a model's metric+group-by/time-series, against the
bundled demo dataset, an uploaded .duckdb file, or a persisted named Connection
(duckdb_file or snowflake - see connection_runtime.py). Also exposes a download of
the demo dataset itself as a real .duckdb file (`demo_router`), so it can seed the
Upload mode or a duckdb_file connection - the CLI's `export-demo-dataset` command is
the same operation, see `semantica.demo_data.export_demo_dataset`."""

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from semantica._vendor.osi import OSIDialect
from semantica.demo_data import export_demo_dataset
from semantica.parser import parse_osi_yaml
from semantica.resolved_model import ResolvedModel
from semantica_api.config import settings
from semantica_api.connection_runtime import emitter_for_connection_type, get_connection_or_404, open_connection
from semantica_api.db import get_db
from semantica_api.deps import get_current_user, get_visible_model
from semantica_api.duckdb_runtime import (
    build_tpcds_demo_connection,
    catalog_name_for_upload,
    check_demo_compatible,
    open_uploaded_database,
    run_metric_query,
    run_timeseries_query,
    saved_upload,
)
from semantica_api.models import SemanticModelRecord, User
from semantica_api.query_runtime import run_metric_query as run_metric_query_generic
from semantica_api.query_runtime import run_timeseries_query as run_timeseries_query_generic
from semantica_api.schemas import RunDuckDbOut

router = APIRouter(prefix="/api/models", tags=["duckdb"])
demo_router = APIRouter(prefix="/api/demo-dataset", tags=["duckdb"])

RunMode = Literal["upload", "demo", "connection"]


@demo_router.get("/export")
def export_demo_dataset_endpoint(
    user: User = Depends(get_current_user),  # noqa: ARG001 - requires a resolvable user
) -> FileResponse:
    """Download the bundled demo dataset as a real .duckdb file - the same data the
    "Demo dataset" run mode uses in-memory, so it can be re-uploaded or registered as
    a duckdb_file connection. Builds to a size-unbounded temp file (it's a small fixed
    dataset, not user input) that's deleted once the response finishes streaming."""
    fd, tmp_name = tempfile.mkstemp(dir=settings.upload_tmp_dir, suffix=".duckdb")
    os.close(fd)
    tmp_path = Path(tmp_name)
    export_demo_dataset(tmp_path, overwrite=True)  # mkstemp already created an empty file at tmp_path
    return FileResponse(
        tmp_path,
        media_type="application/octet-stream",
        filename="tpcds-demo.duckdb",
        background=BackgroundTask(tmp_path.unlink, missing_ok=True),
    )


@router.post("/{model_id}/run", response_model=RunDuckDbOut)
def run_duckdb(
    mode: RunMode = Form(...),
    metric: str = Form(...),
    group_by_json: str = Form("[]"),
    connection_id: int | None = Form(None),
    file: UploadFile | None = None,
    db: Session = Depends(get_db),
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
    elif mode == "connection":
        if connection_id is None:
            raise HTTPException(status_code=400, detail="connection_id is required when mode='connection'")
        conn = get_connection_or_404(db, connection_id)
        emitter = emitter_for_connection_type(conn.type)
        with open_connection(conn, model, referenced) as con:
            result = run_metric_query_generic(con, emitter, model, metric, group_by or None)
    else:
        if file is None:
            raise HTTPException(status_code=400, detail="file is required when mode='upload'")
        catalog_name = catalog_name_for_upload(model, referenced)
        with saved_upload(file) as path, open_uploaded_database(path, catalog_name) as con:
            result = run_metric_query(con, model, metric, group_by or None)

    return RunDuckDbOut(**result)


@router.post("/{model_id}/run/timeseries", response_model=RunDuckDbOut)
def run_duckdb_timeseries(
    mode: RunMode = Form(...),
    metric: str = Form(...),
    time_dataset: str = Form(...),
    time_field: str = Form(...),
    grain: str = Form(...),
    filter_grain: str | None = Form(None),
    filter_value: str | None = Form(None),
    connection_id: int | None = Form(None),
    file: UploadFile | None = None,
    db: Session = Depends(get_db),
    record: SemanticModelRecord = Depends(get_visible_model),
) -> RunDuckDbOut:
    """Group a metric by DATE_TRUNC(grain, time_field) - the query behind the Design
    tab's and Run tab's drill-down/roll-up time-series view. `filter_grain`/
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
    elif mode == "connection":
        if connection_id is None:
            raise HTTPException(status_code=400, detail="connection_id is required when mode='connection'")
        conn = get_connection_or_404(db, connection_id)
        emitter = emitter_for_connection_type(conn.type)
        with open_connection(conn, model, referenced) as con:
            result = run_timeseries_query_generic(
                con, emitter, model, metric, time_dataset, time_field, grain, filter_grain, filter_value
            )
    else:
        if file is None:
            raise HTTPException(status_code=400, detail="file is required when mode='upload'")
        catalog_name = catalog_name_for_upload(model, referenced)
        with saved_upload(file) as path, open_uploaded_database(path, catalog_name) as con:
            result = run_timeseries_query(
                con, model, metric, time_dataset, time_field, grain, filter_grain, filter_value
            )

    return RunDuckDbOut(**result)
