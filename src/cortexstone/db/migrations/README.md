# Database migrations

Migration `0001` enables pgvector's `vector` extension and creates the `memory_items` table, including its constraints and owner-scoped, temporal, and HNSW indexes. The embedding column is `VECTOR(384)`, matching the configured BGE-small model.

Apply migrations with `python -m alembic upgrade head`. The migration reads `DATABASE_URL` when set, or falls back to `sqlalchemy.url` in the root `alembic.ini`. Downgrading removes the table and its indexes but intentionally leaves the extension installed because it may be shared by other database objects.

Add subsequent schema changes as new reversible revisions rather than editing an applied migration.
