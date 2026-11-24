"""Database-backed permission grant management."""

from cortexstone.security.permissions.service import (
    PermissionGrantRecord,
    SqlAlchemyPermissionService,
)

__all__ = ["PermissionGrantRecord", "SqlAlchemyPermissionService"]
