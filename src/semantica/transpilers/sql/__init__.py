from .bigquery import BigQueryEmitter
from .databricks import DatabricksEmitter
from .duckdb import DuckDBEmitter
from .postgres import PostgresEmitter
from .snowflake import SnowflakeEmitter

EMITTERS = {
    "duckdb": DuckDBEmitter,
    "postgres": PostgresEmitter,
    "bigquery": BigQueryEmitter,
    "databricks": DatabricksEmitter,
    "snowflake": SnowflakeEmitter,
}

__all__ = [
    "BigQueryEmitter",
    "DatabricksEmitter",
    "DuckDBEmitter",
    "PostgresEmitter",
    "SnowflakeEmitter",
    "EMITTERS",
]
