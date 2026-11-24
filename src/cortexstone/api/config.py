"""Application settings loaded from the process environment."""

from __future__ import annotations

import os
import re
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Settings(BaseModel):
    """Validated runtime configuration for the API."""

    model_config = ConfigDict(frozen=True)

    database_url: str | None = Field(default=None, repr=False)
    notes_search_allowed_targets: tuple[str, ...] = ()
    cors_allowed_origins: tuple[str, ...] = ()
    groq_api_key: str | None = Field(default=None, repr=False)
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_router_model_id: str = "llama-3.3-70b-versatile"
    google_api_key: str | None = Field(default=None, repr=False)
    google_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    google_reasoner_model_id: str = "gemini-2.5-flash"
    auth_issuer: str | None = None
    auth_audience: str | None = None
    auth_jwks_url: str | None = None
    permission_admin_subjects: tuple[str, ...] = ()
    github_token: str | None = Field(default=None, repr=False)
    github_issue_read_allowed_targets: tuple[str, ...] = ()

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

    @field_validator("groq_api_key", "google_api_key")
    @classmethod
    def validate_model_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if value.startswith("your_") and value.endswith("_api_key_here"):
            return None
        return value or None

    @field_validator("github_token")
    @classmethod
    def validate_github_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or value == "your_github_token_here":
            return None
        if any(ord(character) < 33 or ord(character) > 126 for character in value):
            raise ValueError("GitHub token must contain printable non-whitespace characters")
        return value

    @field_validator("github_issue_read_allowed_targets")
    @classmethod
    def validate_github_repositories(cls, targets: tuple[str, ...]) -> tuple[str, ...]:
        repository_pattern = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
        if any(
            not repository_pattern.fullmatch(target)
            or any(
                part in {".", ".."} or len(part) > max_length
                for part, max_length in zip(target.split("/"), (39, 100), strict=True)
            )
            for target in targets
        ):
            raise ValueError("GitHub policy targets must be exact owner/repository names")
        if len(set(targets)) != len(targets):
            raise ValueError("GitHub policy targets must be unique")
        return targets

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

    @field_validator("permission_admin_subjects")
    @classmethod
    def validate_permission_admin_subjects(cls, subjects: tuple[str, ...]) -> tuple[str, ...]:
        if any(not subject or subject != subject.strip() for subject in subjects):
            raise ValueError("Permission administrator subjects must be non-empty and trimmed")
        if len(set(subjects)) != len(subjects):
            raise ValueError("Permission administrator subjects must be unique")
        return subjects

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(origins)) != len(origins):
            raise ValueError("CORS origins must be unique")
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                not origin
                or origin != origin.strip()
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
                or "*" in origin
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins")
        return origins

    @classmethod
    def from_environment(cls) -> Self:
        """Read the API's supported environment configuration."""
        database_url = os.getenv("DATABASE_URL")
        raw_targets = os.getenv("CORTEXSTONE_POLICY_NOTES_SEARCH_TARGETS", "")
        targets = tuple(target.strip() for target in raw_targets.split(",") if target.strip())
        raw_origins = os.getenv("CORTEXSTONE_CORS_ORIGINS", "")
        origins = tuple(origin.strip() for origin in raw_origins.split(",") if origin.strip())
        raw_permission_admins = os.getenv("CORTEXSTONE_PERMISSION_ADMIN_SUBJECTS", "")
        permission_admin_subjects = tuple(
            subject.strip() for subject in raw_permission_admins.split(",") if subject.strip()
        )
        return cls(
            database_url=database_url,
            notes_search_allowed_targets=targets,
            cors_allowed_origins=origins,
            groq_api_key=os.getenv("GROQ_API_KEY"),
            groq_base_url=os.getenv(
                "GROQ_BASE_URL",
                "https://api.groq.com/openai/v1",
            ),
            groq_router_model_id=os.getenv(
                "GROQ_ROUTER_MODEL_ID",
                "llama-3.3-70b-versatile",
            ),
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            google_base_url=os.getenv(
                "GOOGLE_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai",
            ),
            google_reasoner_model_id=os.getenv(
                "GOOGLE_REASONER_MODEL_ID",
                "gemini-2.5-flash",
            ),
            github_token=os.getenv("GITHUB_TOKEN"),
            github_issue_read_allowed_targets=tuple(
                target.strip()
                for target in os.getenv(
                    "CORTEXSTONE_POLICY_GITHUB_ISSUE_READ_TARGETS",
                    "",
                ).split(",")
                if target.strip()
            ),
            auth_issuer=os.getenv("CORTEXSTONE_AUTH_ISSUER"),
            auth_audience=os.getenv("CORTEXSTONE_AUTH_AUDIENCE"),
            auth_jwks_url=os.getenv("CORTEXSTONE_AUTH_JWKS_URL"),
            permission_admin_subjects=permission_admin_subjects,
        )
