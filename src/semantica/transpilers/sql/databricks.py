from semantica._vendor.osi import OSIDialect

from .base import SqlDialectEmitter


class DatabricksEmitter(SqlDialectEmitter):
    dialect = OSIDialect.DATABRICKS
    quote_char = "`"
