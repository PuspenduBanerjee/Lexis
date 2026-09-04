from semantica._vendor.ossie import OssieDialect

from .base import SqlDialectEmitter


class BigQueryEmitter(SqlDialectEmitter):
    dialect = OssieDialect.BIGQUERY
    quote_char = "`"
