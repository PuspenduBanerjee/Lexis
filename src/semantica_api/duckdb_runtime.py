"""Live DuckDB execution: upload handling, the bundled TPC-DS demo dataset, and running
the emitter's generated SQL for real.

Both demo and upload modes run the emitted SQL **unmodified** (no string rewriting):
the model's `source` values are `catalog.schema.table` (e.g. `tpcds.public.store_sales`),
and DuckDB supports attaching a secondary catalog under an explicit name via
`ATTACH ... AS <name>` (including `ATTACH ':memory:' AS tpcds` for an in-memory one) -
so both paths just attach a database under the catalog name the model's SQL expects.

The demo dataset itself (`build_tpcds_demo_connection`/`TPCDS_DEMO_SOURCES`) lives in
`semantica.demo_data` (core library, not this API package) so the CLI's
`export-demo-dataset` command can reuse the exact same CREATE/INSERT statements
without depending on semantica_api.
"""

import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
from fastapi import HTTPException, UploadFile

from semantica.demo_data import TPCDS_DEMO_SOURCES, build_tpcds_demo_connection
from semantica.resolved_model import ResolvedModel
from semantica.transpilers.sql import DuckDBEmitter
from semantica_api.config import settings
from semantica_api.query_runtime import run_metric_query as _run_metric_query
from semantica_api.query_runtime import run_timeseries_query as _run_timeseries_query

__all__ = [
    "build_tpcds_demo_connection",
    "catalog_name_for_upload",
    "check_demo_compatible",
    "open_uploaded_database",
    "run_metric_query",
    "run_timeseries_query",
    "saved_upload",
]

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def check_demo_compatible(model: ResolvedModel, dataset_names: set[str]) -> None:
    for name in dataset_names:
        source = model.datasets[name].source
        if source not in TPCDS_DEMO_SOURCES:
            raise HTTPException(
                status_code=400,
                detail=(
                    "the bundled demo dataset only supports models built on the "
                    "TPC-DS fixture schema (store_sales/customer/item)"
                ),
            )


def catalog_name_for_upload(model: ResolvedModel, dataset_names: set[str]) -> str:
    """The single catalog name (first `.`-segment of `source`) all referenced datasets
    must share for an uploaded single-file database to be attachable at all."""
    catalogs = {model.datasets[name].source.split(".", 1)[0] for name in dataset_names}
    if len(catalogs) != 1:
        raise HTTPException(
            status_code=400,
            detail=(
                "upload mode requires all datasets referenced by this metric/group-by "
                f"to share one catalog name in their `source`; found {sorted(catalogs)}"
            ),
        )
    catalog = catalogs.pop()
    if not _SAFE_IDENTIFIER_RE.match(catalog):
        raise HTTPException(status_code=400, detail=f"invalid catalog name in source: {catalog!r}")
    return catalog


@contextmanager
def saved_upload(file: UploadFile) -> Iterator[Path]:
    """Stream an uploaded .duckdb file to a size-capped temp file, deleted on exit."""
    if not (file.filename or "").endswith((".duckdb", ".db")):
        raise HTTPException(status_code=400, detail="uploaded file must end in .duckdb or .db")

    max_bytes = settings.max_duckdb_upload_mb * 1024 * 1024
    fd, tmp_name = tempfile.mkstemp(dir=settings.upload_tmp_dir, suffix=".duckdb")
    tmp_path = Path(tmp_name)
    try:
        written = 0
        with open(fd, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"upload exceeds {settings.max_duckdb_upload_mb} MB limit",
                    )
                out.write(chunk)
        yield tmp_path
    finally:
        tmp_path.unlink(missing_ok=True)


@contextmanager
def open_uploaded_database(path: Path, catalog_name: str) -> Iterator[duckdb.DuckDBPyConnection]:
    """Attach the uploaded file read-only under `catalog_name` so the model's own
    `catalog.schema.table`-qualified SQL resolves against it without modification."""
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{path}' AS {catalog_name} (READ_ONLY)")
        yield con
    finally:
        con.close()


def run_metric_query(
    con: duckdb.DuckDBPyConnection,
    model: ResolvedModel,
    metric: str,
    group_by: list[str] | None,
) -> dict:
    """Thin DuckDB-flavored wrapper over the driver-agnostic
    `query_runtime.run_metric_query` - kept so demo/upload call sites don't need to
    know or care about emitter selection (always DuckDB here)."""
    return _run_metric_query(con, DuckDBEmitter(), model, metric, group_by)


def run_timeseries_query(
    con: duckdb.DuckDBPyConnection,
    model: ResolvedModel,
    metric: str,
    time_dataset: str,
    time_field: str,
    grain: str,
    filter_grain: str | None,
    filter_value: str | None,
) -> dict:
    return _run_timeseries_query(
        con, DuckDBEmitter(), model, metric, time_dataset, time_field, grain, filter_grain, filter_value
    )
