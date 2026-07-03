from semantica._vendor.osi import OSIDialect

from .base import SqlDialectEmitter


class DuckDBEmitter(SqlDialectEmitter):
    dialect = OSIDialect.ANSI_SQL
    quote_char = '"'
