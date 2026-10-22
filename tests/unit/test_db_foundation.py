"""Tests for core database foundation: Base, naming convention, and session factory."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import Column, Integer, String

from cortexstone.db.base import POSTGRES_NAMING_CONVENTION, Base, TimestampMixin, utc_now
from cortexstone.db.session import (
    create_engine_from_url,
    create_session_factory,
)


class DummyModel(Base, TimestampMixin):
    """Test model inheriting from declarative Base and TimestampMixin."""

    __tablename__ = "dummy_model"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)


def test_naming_convention_present():
    """Verify metadata uses explicit PostgreSQL naming conventions."""
    assert Base.metadata.naming_convention == POSTGRES_NAMING_CONVENTION
    assert "ix" in Base.metadata.naming_convention
    assert "pk" in Base.metadata.naming_convention
    assert "fk" in Base.metadata.naming_convention


def test_utc_now_timezone_aware():
    """Verify utc_now generates timezone-aware UTC datetime."""
    now = utc_now()
    assert isinstance(now, datetime)
    assert now.tzinfo is not None
    assert now.tzinfo == UTC


def test_dummy_model_columns():
    """Verify dummy model correctly attaches table and timestamp columns."""
    assert DummyModel.__tablename__ == "dummy_model"
    table = DummyModel.__table__
    assert "id" in table.c
    assert "name" in table.c
    assert "created_at" in table.c
    assert "updated_at" in table.c
    assert table.c.created_at.type.timezone is True
    assert table.c.updated_at.type.timezone is True


def test_create_engine_empty_url_raises():
    """Verify create_engine_from_url enforces non-empty connection URL."""
    with pytest.raises(ValueError, match="database_url must be provided"):
        create_engine_from_url("")


def test_session_factory_creation():
    """Verify session factory configuration with an async engine mock/proxy."""
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncEngine

    mock_engine = MagicMock(spec=AsyncEngine)
    session_factory = create_session_factory(mock_engine)
    assert session_factory is not None
    assert session_factory.kw.get("expire_on_commit") is False
    assert session_factory.kw.get("autocommit") is False
    assert session_factory.kw.get("autoflush") is False
