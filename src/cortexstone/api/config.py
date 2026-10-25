"""Application settings loaded from the process environment."""

from __future__ import annotations

import os
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Settings(BaseModel):
    """Validated runtime configuration for the API."""

    model_config = ConfigDict(frozen=True)

    database_url: str | None = Field(default=None, repr=False)
    notes_search_allowed_targets: tuple[str, ...] = ()
    nebius_api_key: str | None = Field(default=None, repr=False)
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    nebius_router_model_id: str = "nvidia/nemotron-mini-4b-instruct"
    nebius_reasoner_model_id: str = "nvidia/nemotron-3-super-120b-a12b"
    auth_issuer: str | None = None
    auth_audience: str | None = None
    auth_jwks_url: str | None = None

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, database_url: str | None) -> str | None:
        if database_url is None:
            return None
        database_url = database_url.strip()
        return database_url or None

    @field_validator("auth_issuer", "auth_audience", "auth_jwks_url")
    @classmethod
    def validate_auth_settings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("nebius_api_key")
    @classmethod
    def validate_nebius_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if value == "your_nebius_api_key_here":
            return None
        return value or None

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> Self:
        auth_values = (self.auth_issuer, self.auth_audience, self.auth_jwks_url)
        if any(auth_values) and not all(auth_values):
            raise ValueError(
                "CORTEXSTONE_AUTH_ISSUER, CORTEXSTONE_AUTH_AUDIENCE, and "
                "CORTEXSTONE_AUTH_JWKS_URL must be configured together"
            )
        for setting_name, value in (
            ("auth_issuer", self.auth_issuer),
            ("auth_jwks_url", self.auth_jwks_url),
        ):
            if value is not None:
                parsed = urlsplit(value)
                if parsed.scheme != "https" or not parsed.netloc:
                    raise ValueError(f"{setting_name} must be an HTTPS URL")
        return self

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
        return cls(
            database_url=database_url,
            notes_search_allowed_targets=targets,
            nebius_api_key=os.getenv("NEBIUS_API_KEY"),
            nebius_base_url=os.getenv(
                "NEBIUS_BASE_URL",
                "https://api.tokenfactory.nebius.com/v1",
            ),
            nebius_router_model_id=os.getenv(
                "NEBIUS_ROUTER_MODEL_ID",
                "nvidia/nemotron-mini-4b-instruct",
            ),
            nebius_reasoner_model_id=os.getenv(
                "NEBIUS_REASONER_MODEL_ID",
                "nvidia/nemotron-3-super-120b-a12b",
            ),
            auth_issuer=os.getenv("CORTEXSTONE_AUTH_ISSUER"),
            auth_audience=os.getenv("CORTEXSTONE_AUTH_AUDIENCE"),
            auth_jwks_url=os.getenv("CORTEXSTONE_AUTH_JWKS_URL"),
        )
