"""Database foundational base models and declarative metadata.

All SQLAlchemy declarative models inherit from Base.
Provides audit timestamps (created_at, updated_at) in strict UTC.
"""

from datetime import datetime, timezone
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime

# Convention for deterministic, explicit database constraint naming
POSTGRES_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    """Return current UTC timestamp with timezone awareness."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base class for all CortexStone persistence models."""

    metadata = MetaData(naming_convention=POSTGRES_NAMING_CONVENTION)


class TimestampMixin:
    """Mixin providing created_at and updated_at UTC timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
