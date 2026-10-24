"""Application settings loaded from the process environment."""

from __future__ import annotations

import os
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Settings(BaseModel):
    """Validated runtime configuration for the API."""

    model_config = ConfigDict(frozen=True)

    database_url: str | None = Field(default=None, repr=False)
    notes_search_allowed_targets: tuple[str, ...] = ()

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, database_url: str | None) -> str | None:
        if database_url is None:
            return None
        database_url = database_url.strip()
        return database_url or None

    @field_validator("notes_search_allowed_targets")
    @classmethod
    def validate_notes_targets(cls, targets: tuple[str, ...]) -> tuple[str, ...]:
        if any(not target or target != target.strip() for target in targets):
            raise ValueError("Configured policy targets must be non-empty and trimmed")
        if len(set(targets)) != len(targets):
            raise ValueError("Configured policy targets must be unique")
        return targets

    @classmethod
    def from_environment(cls) -> Self:
        """Read the API's supported environment configuration."""
        database_url = os.getenv("DATABASE_URL")
        raw_targets = os.getenv("CORTEXSTONE_POLICY_NOTES_SEARCH_TARGETS", "")
        targets = tuple(target.strip() for target in raw_targets.split(",") if target.strip())
        return cls(database_url=database_url, notes_search_allowed_targets=targets)
