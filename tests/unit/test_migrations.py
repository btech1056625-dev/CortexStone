"""Unit tests for database migration infrastructure and offline DDL generation."""

from pathlib import Path

import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config


@pytest.fixture
def alembic_cfg() -> Config:
    """Fixture providing Alembic Config pointing to project root alembic.ini."""
    root_dir = Path(__file__).resolve().parents[2]
    ini_path = root_dir / "alembic.ini"
    assert ini_path.is_file(), f"alembic.ini not found at {ini_path}"
    cfg = Config(str(ini_path))
    return cfg


def test_alembic_configuration(alembic_cfg: Config) -> None:
    """Verify alembic.ini points to valid migrations directory and versions."""
    script_loc = alembic_cfg.get_main_option("script_location")
    assert script_loc == "src/cortexstone/db/migrations"

    root_dir = Path(__file__).resolve().parents[2]
    migrations_dir = root_dir / script_loc
    assert migrations_dir.is_dir()

    versions_dir = migrations_dir / "versions"
    assert versions_dir.is_dir()
    version_files = list(versions_dir.glob("*.py"))
    assert len(version_files) >= 1
    assert any("0001" in f.name for f in version_files)


def test_offline_upgrade_sql_generation(alembic_cfg: Config, capsys) -> None:
    """Verify offline upgrade emits CREATE EXTENSION vector, VECTOR(384), and HNSW index."""
    # Execute offline upgrade generation to head
    upgrade(alembic_cfg, "head", sql=True)
    captured = capsys.readouterr()
    sql_text = captured.out

    # Invariant checks:
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in sql_text
    assert "CREATE TABLE memory_items" in sql_text
    assert "VECTOR(384)" in sql_text
    assert "ck_memory_items_kind_valid" in sql_text
    assert "ck_memory_items_confidence_range" in sql_text
    assert "ck_memory_items_sensitivity_valid" in sql_text
    assert "ix_memory_items_owner_id" in sql_text
    assert "ix_memory_items_deleted_at" in sql_text
    assert "ix_memory_items_owner_kind_active" in sql_text
    assert "ix_memory_items_owner_occurred_at" in sql_text
    assert "ix_memory_items_embedding_hnsw" in sql_text
    assert "USING hnsw (embedding vector_cosine_ops)" in sql_text
    assert "WITH (m = 16, ef_construction = 64)" in sql_text
    assert "WHERE deleted_at IS NULL AND embedding IS NOT NULL" in sql_text


def test_offline_downgrade_sql_generation(alembic_cfg: Config, capsys) -> None:
    """Verify offline downgrade emits DROP INDEX and DROP TABLE memory_items."""
    # Execute offline downgrade generation
    downgrade(alembic_cfg, "0001:base", sql=True)
    captured = capsys.readouterr()
    sql_text = captured.out

    assert "DROP INDEX ix_memory_items_embedding_hnsw;" in sql_text
    assert "DROP INDEX ix_memory_items_owner_occurred_at;" in sql_text
    assert "DROP INDEX ix_memory_items_owner_kind_active;" in sql_text
    assert "DROP INDEX ix_memory_items_deleted_at;" in sql_text
    assert "DROP INDEX ix_memory_items_owner_id;" in sql_text
    assert "DROP TABLE memory_items;" in sql_text
