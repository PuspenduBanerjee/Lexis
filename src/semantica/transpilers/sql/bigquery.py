from semantica._vendor.osi import OSIDialect

from .base import SqlDialectEmitter


class BigQueryEmitter(SqlDialectEmitter):
    # OSI defines no dedicated BIGQUERY dialect; falls back to ANSI_SQL expression text,
    # with BigQuery's backtick identifier quoting.
    dialect = OSIDialect.ANSI_SQL
    quote_char = "`"
