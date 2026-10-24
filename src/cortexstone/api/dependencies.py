"""FastAPI dependencies for policy services and trusted identity context."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from cortexstone.db.session import get_db_session as yield_db_session
from cortexstone.security.policy import (
    ActionScope,
    PolicyEngine,
    PolicyPrincipal,
    RiskLevel,
    ToolPolicy,
)


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped SQLAlchemy session from the application factory."""
    session_factory = request.app.state.db_session_factory
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured.",
        )

    async with asynccontextmanager(yield_db_session)(session_factory) as session:
        yield session


def get_policy_engine(request: Request) -> PolicyEngine:
    """Resolve the application-scoped policy engine."""
    return request.app.state.policy_engine


def get_policy_principal() -> PolicyPrincipal:
    """Fail closed until authentication can provide a trusted principal."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication is not configured.",
    )


def build_policy_engine(allowed_targets: tuple[str, ...]) -> PolicyEngine:
    """Create policies from validated server configuration."""
    policies = []
    if allowed_targets:
        policies.append(
            ToolPolicy(
                tool_name="notes.search",
                scope=ActionScope.READ,
                risk=RiskLevel.LOW,
                allowed_targets=frozenset(allowed_targets),
                required_arguments=frozenset({"query"}),
                optional_arguments=frozenset({"limit"}),
            )
        )
    return PolicyEngine(policies)
