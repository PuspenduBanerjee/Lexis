"""SQLAlchemy ORM models: User, Role, SemanticModelRecord.

Named `SemanticModelRecord` (not `SemanticModel`) to avoid confusion with
`semantica._vendor.osi.OSISemanticModel`, which shows up in the same import graph
when routes parse `raw_yaml` back into a live OSI document.
"""

import enum
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from semantica_api.db import Base


class Role(str, enum.Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True, index=True)
    role: Mapped[Role] = mapped_column(SAEnum(Role), default=Role.VIEWER)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    models: Mapped[list["SemanticModelRecord"]] = relationship(back_populates="owner")


class SemanticModelRecord(Base):
    __tablename__ = "semantic_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    raw_yaml: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    owner: Mapped["User"] = relationship(back_populates="models")
