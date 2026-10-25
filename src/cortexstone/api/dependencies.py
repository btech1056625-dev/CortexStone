"""FastAPI dependencies for policy services and trusted identity context."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from cortexstone.agent.models.interface import ModelClient
from cortexstone.agent.orchestration.orchestrator import AgentOrchestrator
from cortexstone.api.auth import (
    AuthenticatedUser,
    AuthenticationProviderUnavailable,
    InvalidBearerToken,
)
from cortexstone.application.chat.service import ChatService
from cortexstone.application.memory.service import MemoryService
from cortexstone.db.session import get_db_session as yield_db_session
from cortexstone.memory.repositories.memory_repo import SqlAlchemyMemoryRepository
from cortexstone.security.policy import (
    ActionScope,
    PolicyEngine,
    PolicyPrincipal,
    RiskLevel,
    ToolPolicy,
)

bearer_scheme = HTTPBearer(auto_error=False)


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


def get_model_client(request: Request) -> ModelClient:
    """Resolve the configured model provider without substituting a demo client."""
    model_client = request.app.state.model_client
    if model_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model provider is not configured.",
        )
    return model_client


def get_agent_orchestrator(
    model_client: Annotated[ModelClient, Depends(get_model_client)],
) -> AgentOrchestrator:
    """Build the agent orchestration boundary over the configured model provider."""
    return AgentOrchestrator(model_client)


def get_authenticated_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ] = None,
) -> AuthenticatedUser:
    """Resolve identity only from a verified OIDC bearer token."""
    authenticator = request.app.state.authenticator
    if authenticator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return authenticator.authenticate(credentials.credentials)
    except InvalidBearerToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except AuthenticationProviderUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication provider is unavailable.",
        ) from None


def get_policy_principal(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> PolicyPrincipal:
    """Resolve the authenticated subject into a fail-closed policy principal."""
    return PolicyPrincipal(principal_id=user.subject, grants=())


def get_memory_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemoryService:
    """Build a request-scoped memory service over the authenticated request's session."""
    repository = SqlAlchemyMemoryRepository(session)
    return MemoryService(
        repository=repository,
        embedding_provider=request.app.state.memory_embedding_provider,
    )


def get_chat_service(
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    agent: Annotated[AgentOrchestrator, Depends(get_agent_orchestrator)],
) -> ChatService:
    """Build the chat use case with request-scoped memory and the configured agent."""
    return ChatService(memory_service=memory_service, agent=agent)


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
