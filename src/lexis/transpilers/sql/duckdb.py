from semantica._vendor.ossie import OssieDialect

from .base import SqlDialectEmitter


class DuckDBEmitter(SqlDialectEmitter):
    dialect = OssieDialect.ANSI_SQL
    quote_char = '"'
