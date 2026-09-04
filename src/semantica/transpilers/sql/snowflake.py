from semantica._vendor.ossie import OssieDialect

from .base import SqlDialectEmitter


class SnowflakeEmitter(SqlDialectEmitter):
    dialect = OssieDialect.SNOWFLAKE
    quote_char = '"'
