"""Execution against a persisted `Connection` (duckdb_file or snowflake) - distinct
from `duckdb_runtime.py`'s demo/upload modes, which need no persisted config.

Iceberg isn't supported here yet - see TODO.md for why (it isn't a SQL dialect the
app already emits; "Iceberg" really means picking a catalog type (Glue/REST/Hive)
plus a query engine, a separate design decision).
"""

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb
import snowflake.connector
from fastapi import HTTPException
from sqlalchemy.orm import Session

from lexis.resolved_model import ResolvedModel
from lexis.transpilers.sql import DuckDBEmitter, SnowflakeEmitter
from lexis.transpilers.sql.base import SqlDialectEmitter
from lexis_api.models import Connection, ConnectionType

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_REQUIRED_CONFIG_KEYS: dict[ConnectionType, set[str]] = {
    ConnectionType.DUCKDB_FILE: {"path"},
    ConnectionType.SNOWFLAKE: {"account", "user", "password_env"},
}
_OPTIONAL_CONFIG_KEYS: dict[ConnectionType, set[str]] = {
    ConnectionType.DUCKDB_FILE: set(),
    ConnectionType.SNOWFLAKE: {"warehouse", "database", "schema", "role"},
}


def validate_connection_config(conn_type: ConnectionType, config: dict) -> None:
    """Raises ValueError (-> 422 via main.py's global handler) on a malformed
    config, so bad connections are caught at create/update time, not on first run."""
    required = _REQUIRED_CONFIG_KEYS[conn_type]
    missing = required - config.keys()
    if missing:
        raise ValueError(f"{conn_type.value} connection config missing required key(s): {sorted(missing)}")
    allowed = required | _OPTIONAL_CONFIG_KEYS[conn_type]
    unknown = config.keys() - allowed
    if unknown:
        raise ValueError(f"{conn_type.value} connection config has unknown key(s): {sorted(unknown)}")
    for key, value in config.items():
        if not isinstance(value, str):
            raise ValueError(f"{conn_type.value} connection config key {key!r} must be a string")


def get_connection_or_404(db: Session, connection_id: int) -> Connection:
    """Any authenticated user can run against any connection (same workspace-wide
    visibility as models - see `get_visible_connection` in deps.py, the equivalent
    used for the connections CRUD routes' path-param form of this same lookup)."""
    record = db.get(Connection, connection_id)
    if record is None:
        raise HTTPException(status_code=422, detail=f"unknown connection id {connection_id!r}")
    return record


def emitter_for_connection_type(conn_type: ConnectionType) -> SqlDialectEmitter:
    if conn_type == ConnectionType.DUCKDB_FILE:
        return DuckDBEmitter()
    if conn_type == ConnectionType.SNOWFLAKE:
        return SnowflakeEmitter()
    raise ValueError(f"Unsupported connection type: {conn_type!r}")


def catalog_name_for_datasets(model: ResolvedModel, dataset_names: set[str]) -> str:
    """A duckdb_file connection is one file, so - same requirement as
    `duckdb_runtime.catalog_name_for_upload` - every dataset referenced by a query
    must share one catalog name (the first `.`-segment of `source`)."""
    catalogs = {model.datasets[name].source.split(".", 1)[0] for name in dataset_names}
    if len(catalogs) != 1:
        raise HTTPException(
            status_code=400,
            detail=(
                "a duckdb_file connection requires all datasets referenced by this "
                f"metric/group-by to share one catalog name in their `source`; found {sorted(catalogs)}"
            ),
        )
    catalog = catalogs.pop()
    if not _SAFE_IDENTIFIER_RE.match(catalog):
        raise HTTPException(status_code=400, detail=f"invalid catalog name in source: {catalog!r}")
    return catalog


@contextmanager
def open_duckdb_file_connection(config: dict, catalog_name: str) -> Iterator[duckdb.DuckDBPyConnection]:
    """Attach a server-side DuckDB file (already on disk, not uploaded) read-only
    under `catalog_name`, so the model's `catalog.schema.table`-qualified SQL
    resolves against it unmodified - same trick as `duckdb_runtime.open_uploaded_database`."""
    path = Path(config["path"])
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"no such file on the API server: {config['path']!r}")
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{path}' AS {catalog_name} (READ_ONLY)")
        yield con
    finally:
        con.close()


def _snowflake_password(config: dict) -> str:
    password_env = config["password_env"]
    password = os.environ.get(password_env)
    if not password:
        raise HTTPException(
            status_code=400,
            detail=(
                f"environment variable {password_env!r} (this connection's password_env) "
                "is not set on the API server"
            ),
        )
    return password


@contextmanager
def open_snowflake_connection(config: dict) -> Iterator[Any]:
    """Connects with the model's `source` (`database.schema.table`) used as-is in
    the emitted SQL - unlike DuckDB's ATTACH-based catalog renaming, Snowflake
    already supports fully-qualified 3-part object names natively, so no
    catalog-name juggling is needed here."""
    try:
        con = snowflake.connector.connect(
            account=config["account"],
            user=config["user"],
            password=_snowflake_password(config),
            warehouse=config.get("warehouse"),
            database=config.get("database"),
            schema=config.get("schema"),
            role=config.get("role"),
        )
    except snowflake.connector.errors.Error as exc:
        raise HTTPException(status_code=400, detail=f"could not connect to Snowflake: {exc}") from exc
    try:
        yield con
    finally:
        con.close()


@contextmanager
def open_connection(conn: Connection, model: ResolvedModel, dataset_names: set[str]) -> Iterator[Any]:
    """Dispatches to the right opener for `conn.type`. `dataset_names` is only used
    by duckdb_file (to derive the attach catalog name); ignored for snowflake."""
    if conn.type == ConnectionType.DUCKDB_FILE:
        catalog_name = catalog_name_for_datasets(model, dataset_names)
        with open_duckdb_file_connection(conn.config, catalog_name) as con:
            yield con
    elif conn.type == ConnectionType.SNOWFLAKE:
        with open_snowflake_connection(conn.config) as con:
            yield con
    else:
        raise ValueError(f"Unsupported connection type: {conn.type!r}")


def test_connection(conn: Connection) -> dict:
    """Best-effort connectivity check for the 'Test connection' UI action - opens
    (and, for duckdb_file, immediately closes) a real connection without running
    any query against the model."""
    try:
        if conn.type == ConnectionType.DUCKDB_FILE:
            path = Path(conn.config["path"])
            if not path.is_file():
                return {"ok": False, "detail": f"no such file on the API server: {conn.config['path']!r}"}
            con = duckdb.connect(str(path), read_only=True)
            con.close()
            return {"ok": True, "detail": "file opened successfully"}
        if conn.type == ConnectionType.SNOWFLAKE:
            with open_snowflake_connection(conn.config):
                pass
            return {"ok": True, "detail": "connected successfully"}
        return {"ok": False, "detail": f"unsupported connection type: {conn.type!r}"}
    except HTTPException as exc:
        return {"ok": False, "detail": str(exc.detail)}
    except duckdb.Error as exc:
        return {"ok": False, "detail": f"could not open file: {exc}"}
