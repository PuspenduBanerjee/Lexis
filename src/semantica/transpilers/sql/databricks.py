from semantica._vendor.ossie import OssieDialect

from .base import SqlDialectEmitter


class DatabricksEmitter(SqlDialectEmitter):
    dialect = OssieDialect.DATABRICKS
    quote_char = "`"
