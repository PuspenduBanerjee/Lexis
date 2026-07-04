"""Live DuckDB execution: upload handling, the bundled TPC-DS demo dataset, and running
the emitter's generated SQL for real.

Both demo and upload modes run the emitted SQL **unmodified** (no string rewriting):
the model's `source` values are `catalog.schema.table` (e.g. `tpcds.public.store_sales`),
and DuckDB supports attaching a secondary catalog under an explicit name via
`ATTACH ... AS <name>` (including `ATTACH ':memory:' AS tpcds` for an in-memory one) -
so both paths just attach a database under the catalog name the model's SQL expects.

Note on the demo dataset: the plan called for sharing this setup with
`tests/test_sql_emitters.py`'s existing DuckDB fixture data via a helper under
`tests/fixtures/`. That would make this production module depend on the `tests/`
tree, which isn't packaged/shipped and is the wrong dependency direction (production
code should not import from tests). Instead, `build_tpcds_demo_connection()` lives
here (production code, since the demo-mode feature genuinely needs it at runtime),
duplicating the same small, stable set of CREATE/INSERT statements the existing unit
test already uses. The new API test (`tests/api/test_duckdb_execution.py`) imports
this function directly instead of re-duplicating a third copy.
"""

import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import duckdb
from fastapi import HTTPException, UploadFile

from semantica.resolved_model import ResolvedModel
from semantica.transpilers.sql import DuckDBEmitter
from semantica_api.config import settings

_TPCDS_DEMO_SOURCES = {
    "tpcds.public.store_sales",
    "tpcds.public.customer",
    "tpcds.public.item",
    "tpcds.public.date_dim",
}
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def build_tpcds_demo_connection() -> duckdb.DuckDBPyConnection:
    """A small bundled in-memory dataset matching the TPC-DS fixture's schema, attached
    under catalog `tpcds` so `tpcds.public.*`-sourced SQL runs against it unmodified.

    The `date_dim`/time-series rows use `ss_item_sk=12`/`ss_customer_sk=102`, which
    deliberately don't match any `item`/`customer` row - so they're silently excluded
    by the INNER JOINs in `test_demo_mode_matches_unit_test_result`'s Books/Electronics
    query, and only show up for metrics that don't join those tables (e.g.
    `total_sales`, grouped/drilled by date_dim's `d_date`).
    """
    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS tpcds")
    con.execute("CREATE SCHEMA tpcds.public")
    con.execute(
        "CREATE TABLE tpcds.public.store_sales ("
        "ss_sold_date_sk INT, ss_item_sk INT, ss_customer_sk INT, ss_store_sk INT, "
        "ss_ext_sales_price DOUBLE, ss_net_profit DOUBLE)"
    )
    con.execute("CREATE TABLE tpcds.public.customer (c_customer_sk INT)")
    con.execute("CREATE TABLE tpcds.public.item (i_item_sk INT, i_category VARCHAR)")
    con.execute(
        "CREATE TABLE tpcds.public.date_dim ("
        "d_date_sk INT, d_date DATE, d_year INT, d_quarter_name VARCHAR, d_month_name VARCHAR)"
    )
    con.execute(
        "INSERT INTO tpcds.public.store_sales VALUES "
        "(1,10,100,1000,50.0,5.0),(1,11,101,1000,30.0,3.0),(2,10,100,1001,20.0,2.0),"
        "(3,12,102,1000,40.0,4.0),(4,12,102,1000,60.0,6.0),(5,12,102,1000,25.0,2.5),(6,12,102,1000,35.0,3.5)"
    )
    con.execute("INSERT INTO tpcds.public.customer VALUES (100),(101)")
    con.execute("INSERT INTO tpcds.public.item VALUES (10,'Electronics'),(11,'Books')")
    con.execute(
        "INSERT INTO tpcds.public.date_dim VALUES "
        "(1,DATE '2023-01-15',2023,'2023Q1','January'),"
        "(2,DATE '2023-04-20',2023,'2023Q2','April'),"
        "(3,DATE '2023-07-10',2023,'2023Q3','July'),"
        "(4,DATE '2023-10-05',2023,'2023Q4','October'),"
        "(5,DATE '2024-01-18',2024,'2024Q1','January'),"
        "(6,DATE '2024-04-22',2024,'2024Q2','April')"
    )
    return con


def check_demo_compatible(model: ResolvedModel, dataset_names: set[str]) -> None:
    for name in dataset_names:
        source = model.datasets[name].source
        if source not in _TPCDS_DEMO_SOURCES:
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


def _json_safe(value):
    """`date`/`datetime` cells (e.g. a `DATE_TRUNC` period column) aren't natively
    JSON-serializable inside the `rows: list[list[Any]]` response - stringify them
    explicitly here rather than relying on FastAPI's encoder to reach into `Any`."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def run_metric_query(
    con: duckdb.DuckDBPyConnection,
    model: ResolvedModel,
    metric: str,
    group_by: list[str] | None,
) -> dict:
    sql = DuckDBEmitter().emit_metric_query(model, metric, group_by=group_by)
    cursor = con.execute(sql)
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchmany(settings.max_result_rows)
    return {
        "columns": columns,
        "rows": [[_json_safe(v) for v in r] for r in rows],
        "row_count": len(rows),
        "sql": sql,
    }


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
    sql = DuckDBEmitter().emit_timeseries_query(
        model, metric, time_dataset, time_field, grain,
        filter_grain=filter_grain, filter_value=filter_value,
    )
    cursor = con.execute(sql)
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchmany(settings.max_result_rows)
    return {
        "columns": columns,
        "rows": [[_json_safe(v) for v in r] for r in rows],
        "row_count": len(rows),
        "sql": sql,
    }
