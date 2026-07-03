from semantica._vendor.osi import OSIDialect

from .base import SqlDialectEmitter


class PostgresEmitter(SqlDialectEmitter):
    # OSI defines no dedicated POSTGRES dialect; Postgres is ANSI_SQL-compliant enough
    # that the ANSI_SQL expression text is used directly.
    dialect = OSIDialect.ANSI_SQL
    quote_char = '"'
