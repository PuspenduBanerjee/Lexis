"""Driver-agnostic query execution: given any DB-API-style connection (DuckDB,
snowflake-connector-python, ...) and the dialect emitter that matches it, runs a
metric/timeseries query and returns a JSON-safe result dict.

Connection *setup* (attaching a DuckDB file under the right catalog name, opening
a Snowflake session, building the in-memory demo dataset, ...) is mode-specific and
lives in `duckdb_runtime.py` (demo/upload) and `connection_runtime.py` (persisted
named connections) - this module only relies on the `cursor()` ->
`execute()`/`description`/`fetchmany()` shape every PEP 249-ish driver implements,
so the same two functions serve every mode.
"""

from datetime import date, datetime
from typing import Any

from semantica.resolved_model import ResolvedModel
from semantica.transpilers.sql.base import SqlDialectEmitter
from semantica_api.config import settings


def _json_safe(value: Any) -> Any:
    """`date`/`datetime` cells (e.g. a `DATE_TRUNC` period column) aren't natively
    JSON-serializable inside the `rows: list[list[Any]]` response - stringify them
    explicitly here rather than relying on FastAPI's encoder to reach into `Any`."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _fetch_result(cursor: Any) -> dict:
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchmany(settings.max_result_rows)
    return {
        "columns": columns,
        "rows": [[_json_safe(v) for v in r] for r in rows],
        "row_count": len(rows),
    }


def run_metric_query(
    con: Any,
    emitter: SqlDialectEmitter,
    model: ResolvedModel,
    metric: str,
    group_by: list[str] | None,
) -> dict:
    sql = emitter.emit_metric_query(model, metric, group_by=group_by)
    cursor = con.cursor()
    cursor.execute(sql)
    return {**_fetch_result(cursor), "sql": sql}


def run_timeseries_query(
    con: Any,
    emitter: SqlDialectEmitter,
    model: ResolvedModel,
    metric: str,
    time_dataset: str,
    time_field: str,
    grain: str,
    filter_grain: str | None,
    filter_value: str | None,
) -> dict:
    sql = emitter.emit_timeseries_query(
        model, metric, time_dataset, time_field, grain,
        filter_grain=filter_grain, filter_value=filter_value,
    )
    cursor = con.cursor()
    cursor.execute(sql)
    return {**_fetch_result(cursor), "sql": sql}
