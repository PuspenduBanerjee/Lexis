from semantica._vendor.ossie import OssieDialect

from .base import SqlDialectEmitter


class PostgresEmitter(SqlDialectEmitter):
    # Ossie defines no dedicated POSTGRES dialect; Postgres is ANSI_SQL-compliant enough
    # that the ANSI_SQL expression text is used directly.
    dialect = OssieDialect.ANSI_SQL
    quote_char = '"'
