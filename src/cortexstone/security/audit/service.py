"""Audit interfaces and schemas for security and lifecycle event logging.

Ensures sensitive memory contents and secrets are never stored in audit logs.
Audit events record metadata only (who, when, what event, which record ID, status).
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from cortexstone.db.base import utc_now


class AuditEvent(BaseModel):
    """Structured audit event.

    Strictly forbids raw private content or embeddings.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: str = Field(
        ...,
        description="Type of event: e.g., 'memory.forget', 'memory.create', 'memory.update'.",
    )
    owner_id: str = Field(
        ...,
        description="Authenticated owner identity.",
    )
    resource_id: Optional[UUID] = Field(
        default=None,
        description="ID of the resource being acted upon.",
    )
    occurred_at: datetime = Field(
        default_factory=utc_now,
        description="UTC timestamp of the event.",
    )
    status: str = Field(
        default="success",
        description="Status of the operation: 'success', 'failure', 'rejected'.",
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Content-free metadata (e.g. kind, reason code, verification status).",
    )


class AuditLoggerInterface(ABC):
    """Interface for emitting audit log events."""

    @abstractmethod
    async def log_event(self, event: AuditEvent) -> None:
        """Record an audit event.

        Args:
            event: Structured AuditEvent instance.
        """
        raise NotImplementedError


class InMemoryAuditLogger(AuditLoggerInterface):
    """In-memory audit logger implementation for testing and development.

    NOTE ON PERSISTENCE LIMITATION:
    This logger holds events in process memory. It does not provide durable
    database persistence across crashes or server restarts. Durable persistence
    will be provided by the database audit subsystem once implemented.
    """

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def log_event(self, event: AuditEvent) -> None:
        self.events.append(event)
