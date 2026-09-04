"""Bundled TPC-DS-shaped demo dataset: small enough to build in-memory, real enough
to exercise the join graph in `tests/fixtures/tpcds_semantic_model.yaml`. Shared by
the CLI's `export-demo-dataset` command and semantica_api's "Demo dataset" run mode,
so there's exactly one copy of the CREATE/INSERT statements.

Requires the optional `duckdb` dependency - not one of the core `semantica` package's
own dependencies, since the CLI's `transpile` command doesn't need it. Importing this
module (rather than just the `semantica` package) is what opts a caller into that
dependency; see `cli.py`'s lazy import in `export-demo-dataset`.
"""

from pathlib import Path

import duckdb

TPCDS_DEMO_SOURCES = {
    "tpcds.public.store_sales",
    "tpcds.public.customer",
    "tpcds.public.item",
    "tpcds.public.date_dim",
}


def build_tpcds_demo_connection(target: str = ":memory:") -> duckdb.DuckDBPyConnection:
    """Attaches `target` (an in-memory database by default, or a real file path) under
    catalog `tpcds`, so `tpcds.public.*`-sourced SQL runs against it unmodified - and
    for a file `target`, closing the returned connection leaves that data on disk
    (see `export_demo_dataset`, which is exactly this).

    The `date_dim`/time-series rows use `ss_item_sk=12`/`ss_customer_sk=102`, which
    deliberately don't match any `item`/`customer` row - so they're silently excluded
    by the INNER JOINs in `test_demo_mode_matches_unit_test_result`'s Books/Electronics
    query, and only show up for metrics that don't join those tables (e.g.
    `total_sales`, grouped/drilled by date_dim's `d_date`).
    """
    con = duckdb.connect()
    con.execute(f"ATTACH '{target}' AS tpcds")
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


def export_demo_dataset(path: str | Path, *, overwrite: bool = False) -> None:
    """Write the demo dataset to a real .duckdb file at `path` - the same schema/rows
    `build_tpcds_demo_connection()` builds in-memory, so the exported file can be
    re-uploaded (the web UI's Upload run mode) or registered as a `duckdb_file`
    connection and produce identical query results."""
    path = Path(path)
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"{path} already exists")
        path.unlink()
    build_tpcds_demo_connection(target=str(path)).close()
