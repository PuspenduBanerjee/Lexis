"""SQLAlchemy ORM models: User, Role, SemanticModelRecord, Connection.

Named `SemanticModelRecord` (not `SemanticModel`) to avoid confusion with
`semantica._vendor.ossie.OssieSemanticModel`, which shows up in the same import graph
when routes parse `raw_yaml` back into a live Ossie document.
"""

import enum
from datetime import datetime

from sqlalchemy import JSON
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from semantica_api.db import Base


class Role(str, enum.Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class ConnectionType(str, enum.Enum):
    DUCKDB_FILE = "duckdb_file"
    SNOWFLAKE = "snowflake"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True, index=True)
    role: Mapped[Role] = mapped_column(SAEnum(Role), default=Role.VIEWER)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    models: Mapped[list["SemanticModelRecord"]] = relationship(back_populates="owner")
    connections: Mapped[list["Connection"]] = relationship(back_populates="owner")


class SemanticModelRecord(Base):
    __tablename__ = "semantic_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    raw_yaml: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped["User"] = relationship(back_populates="models")


class Connection(Base):
    """A named, reusable datasource config a model's 'Run' can execute against
    (alongside the built-in demo/upload DuckDB modes, which need no persisted
    config). `config` is type-specific JSON - see `schemas.py`'s per-type request
    models for the exact shape. Secrets are never stored here: a Snowflake
    connection's `config` holds a `password_env` (the *name* of an environment
    variable the API process reads at connect time), never the password itself."""

    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    type: Mapped[ConnectionType] = mapped_column(SAEnum(ConnectionType))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped["User"] = relationship(back_populates="connections")
