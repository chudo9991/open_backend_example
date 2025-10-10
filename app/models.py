"""SQLAlchemy models for the demo application."""
from __future__ import annotations

import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, String, func

from .database import Base


class WorkingFormatEnum(str, enum.Enum):
    """Enumeration describing the working format of a user."""

    REMOTE = "remote"
    OFFICE = "office"
    HYBRID = "hybrid"


class User(Base):
    """Represents an employee stored in the ``users`` table."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    name = Column(String(100), nullable=False)
    surname = Column(String(100), nullable=False)
    city = Column(String(100), nullable=True)
    working_format = Column(
        Enum(WorkingFormatEnum, name="working_format_enum", native_enum=False),
        nullable=False,
        default=WorkingFormatEnum.REMOTE,
    )

    def __repr__(self) -> str:  # pragma: no cover - representation helper
        return (
            "User(id={0.id!r}, name={0.name!r}, surname={0.surname!r}, "
            "city={0.city!r}, working_format={0.working_format!r})"
        ).format(self)
