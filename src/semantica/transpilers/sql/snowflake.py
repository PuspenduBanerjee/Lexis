from semantica._vendor.osi import OSIDialect

from .base import SqlDialectEmitter


class SnowflakeEmitter(SqlDialectEmitter):
    dialect = OSIDialect.SNOWFLAKE
    quote_char = '"'
