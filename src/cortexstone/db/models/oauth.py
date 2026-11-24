"""Persistence models for linked OAuth identities and encrypted provider credentials."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from cortexstone.db.base import Base, TimestampMixin


class OAuthIdentityModel(Base, TimestampMixin):
    """Maps an external provider identity to one Cortexstone principal."""

    __tablename__ = "oauth_identities"
    __table_args__ = (
        CheckConstraint("provider IN ('google', 'github')", name="provider_valid"),
        UniqueConstraint("provider", "provider_subject", name="provider_subject_unique"),
        Index("ix_oauth_identities_principal", "principal_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_subject: Mapped[str] = mapped_column(Text, nullable=False)
    principal_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)


class OAuthCredentialModel(Base, TimestampMixin):
    """Encrypted provider tokens used only for the linked principal's connector calls."""

    __tablename__ = "oauth_credentials"
    __table_args__ = (
        CheckConstraint("provider IN ('google', 'github')", name="provider_valid"),
        UniqueConstraint("principal_id", "provider", name="principal_provider_unique"),
        UniqueConstraint("provider", "provider_subject", name="provider_subject_unique"),
        Index("ix_oauth_credentials_expiry", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_subject: Mapped[str] = mapped_column(Text, nullable=False)
    principal_id: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class OAuthFlowModel(Base):
    """Single-use OAuth state and PKCE verifier with a short expiry."""

    __tablename__ = "oauth_flows"
    __table_args__ = (
        CheckConstraint("provider IN ('google', 'github')", name="provider_valid"),
        CheckConstraint("mode IN ('login', 'connect')", name="mode_valid"),
        Index("ix_oauth_flows_expiry", "expires_at"),
    )

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    principal_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_origin: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_code_verifier: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
