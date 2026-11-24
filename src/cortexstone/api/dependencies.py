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
    SESSION_TOKEN_PREFIX,
    AuthenticatedUser,
    AuthenticationProviderUnavailable,
    InvalidBearerToken,
    SessionTokenAuthenticator,
)
from cortexstone.application.chat.service import ChatService
from cortexstone.application.memory.service import MemoryService
from cortexstone.db.session import get_db_session as yield_db_session
from cortexstone.memory.repositories.memory_repo import SqlAlchemyMemoryRepository
from cortexstone.security.action_runs.service import SqlAlchemyActionRunService
from cortexstone.security.approvals.service import SqlAlchemyApprovalService
from cortexstone.security.oauth import OAuthFlowError, OAuthProviderError, OAuthService
from cortexstone.security.permissions.service import SqlAlchemyPermissionService
from cortexstone.security.policy import (
    ActionScope,
    AsyncPermissionService,
    PolicyEngine,
    PolicyPrincipal,
    RiskLevel,
    ToolPolicy,
)
from cortexstone.tools.connectors.github import GITHUB_ISSUE_READ_TOOL, GitHubIssueReader
from cortexstone.tools.connectors.google_calendar import (
    GOOGLE_CALENDAR_EVENT_CREATE_TOOL,
    GOOGLE_CALENDAR_EVENT_DELETE_TOOL,
    GOOGLE_CALENDAR_EVENT_READ_TOOL,
    GOOGLE_CALENDAR_EVENT_UPDATE_TOOL,
    GOOGLE_CALENDAR_SCOPE,
    GoogleCalendarConnector,
)
from cortexstone.tools.runner import ToolRunner

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


def get_permission_service(request: Request) -> SqlAlchemyPermissionService:
    """Resolve durable permission management, failing if persistence is unavailable."""
    permission_service = request.app.state.permission_service
    if permission_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Permission storage is not configured.",
        )
    return permission_service


def get_approval_service(request: Request) -> SqlAlchemyApprovalService:
    """Resolve durable approval management, failing if persistence is unavailable."""
    approval_service = request.app.state.approval_service
    if approval_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Approval storage is not configured.",
        )
    return approval_service


def get_action_run_service(request: Request) -> SqlAlchemyActionRunService:
    """Resolve durable action lifecycle persistence, failing if unavailable."""
    action_run_service = request.app.state.action_run_service
    if action_run_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Action run storage is not configured.",
        )
    return action_run_service


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
    """Resolve identity from a verified OAuth session or configured OIDC bearer token."""
    authenticator = request.app.state.authenticator
    session_authenticator: SessionTokenAuthenticator | None = (
        request.app.state.session_authenticator
    )
    if authenticator is None and session_authenticator is None:
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
        if credentials.credentials.startswith(SESSION_TOKEN_PREFIX):
            if session_authenticator is None:
                raise InvalidBearerToken
            return session_authenticator.authenticate(credentials.credentials)
        if authenticator is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication is not configured.",
            )
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


def get_oauth_service(request: Request) -> OAuthService:
    """Resolve OAuth account management, failing closed when it is not configured."""
    oauth_service = request.app.state.oauth_service
    if oauth_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth providers are not configured.",
        )
    return oauth_service


def get_policy_principal(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> PolicyPrincipal:
    """Resolve the authenticated subject into a fail-closed policy principal."""
    return PolicyPrincipal(principal_id=user.subject, grants=())


async def _build_tool_runner(
    request: Request,
    action_run_service: SqlAlchemyActionRunService,
    user: AuthenticatedUser,
    providers: frozenset[str],
) -> ToolRunner:
    executors = dict(request.app.state.tool_executors)
    settings = request.app.state.settings
    if (
        "github" in providers
        and settings.github_app_client_id is not None
        and settings.github_issue_read_allowed_targets
    ):
        executors.pop(GITHUB_ISSUE_READ_TOOL, None)
        oauth_service: OAuthService | None = request.app.state.oauth_service
        if oauth_service is not None:
            try:
                token = await oauth_service.get_access_token(user.subject, "github")
            except OAuthFlowError:
                pass
            except OAuthProviderError:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The GitHub connection needs to be reauthorized.",
                ) from None
            else:
                github_client = request.app.state.github_http_client
                executors[GITHUB_ISSUE_READ_TOOL] = GitHubIssueReader(
                    token,
                    settings.github_issue_read_allowed_targets,
                    github_client,
                )
    if "google" in providers and settings.google_oauth_client_id is not None:
        for tool_name in (
            GOOGLE_CALENDAR_EVENT_READ_TOOL,
            GOOGLE_CALENDAR_EVENT_CREATE_TOOL,
            GOOGLE_CALENDAR_EVENT_UPDATE_TOOL,
            GOOGLE_CALENDAR_EVENT_DELETE_TOOL,
        ):
            executors.pop(tool_name, None)
        oauth_service = request.app.state.oauth_service
        if oauth_service is not None:
            try:
                token = await oauth_service.get_access_token(
                    user.subject,
                    "google",
                    required_scope=GOOGLE_CALENDAR_SCOPE,
                )
            except OAuthFlowError:
                pass
            except OAuthProviderError:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The Google connection needs to be reauthorized.",
                ) from None
            else:
                calendar_client = request.app.state.google_calendar_http_client
                connector = GoogleCalendarConnector(token, calendar_client)
                executors.update(
                    {
                        GOOGLE_CALENDAR_EVENT_READ_TOOL: connector,
                        GOOGLE_CALENDAR_EVENT_CREATE_TOOL: connector,
                        GOOGLE_CALENDAR_EVENT_UPDATE_TOOL: connector,
                        GOOGLE_CALENDAR_EVENT_DELETE_TOOL: connector,
                    }
                )
    if not executors and not (
        (
            "github" in providers
            and settings.github_app_client_id is not None
            and settings.github_issue_read_allowed_targets
        )
        or ("google" in providers and settings.google_oauth_client_id is not None)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No tool executors are configured.",
        )
    approval_service = request.app.state.approval_service
    return ToolRunner(
        policy_engine=request.app.state.policy_engine,
        executors=executors,
        run_recorder=action_run_service,
        approval_resolver=(
            approval_service.resolve_for_action if approval_service is not None else None
        ),
    )


async def get_tool_runner(
    request: Request,
    action_run_service: Annotated[
        SqlAlchemyActionRunService,
        Depends(get_action_run_service),
    ],
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> ToolRunner:
    """Build a runner with all caller-specific provider executors."""
    return await _build_tool_runner(
        request,
        action_run_service,
        user,
        frozenset({"github", "google"}),
    )


async def get_github_tool_runner(
    request: Request,
    action_run_service: Annotated[
        SqlAlchemyActionRunService,
        Depends(get_action_run_service),
    ],
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> ToolRunner:
    """Build a runner with the caller's linked GitHub credential."""
    return await _build_tool_runner(request, action_run_service, user, frozenset({"github"}))


async def get_google_calendar_tool_runner(
    request: Request,
    action_run_service: Annotated[
        SqlAlchemyActionRunService,
        Depends(get_action_run_service),
    ],
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> ToolRunner:
    """Build a runner with the caller's linked Google Calendar credential."""
    return await _build_tool_runner(request, action_run_service, user, frozenset({"google"}))


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


def build_policy_engine(
    allowed_targets: tuple[str, ...],
    *,
    github_issue_read_allowed_targets: tuple[str, ...] = (),
    github_enabled: bool = False,
    google_calendar_enabled: bool = False,
    async_permission_service: AsyncPermissionService | None = None,
) -> PolicyEngine:
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
    if github_enabled and github_issue_read_allowed_targets:
        policies.append(
            ToolPolicy(
                tool_name="github.issue.read",
                scope=ActionScope.READ,
                risk=RiskLevel.LOW,
                allowed_targets=frozenset(github_issue_read_allowed_targets),
                required_arguments=frozenset({"issue_number"}),
            )
        )
    if google_calendar_enabled:
        policies.extend(
            (
                ToolPolicy(
                    tool_name=GOOGLE_CALENDAR_EVENT_READ_TOOL,
                    scope=ActionScope.READ,
                    risk=RiskLevel.LOW,
                    allowed_targets=frozenset({"primary"}),
                    required_arguments=frozenset({"time_min", "time_max", "time_zone"}),
                    optional_arguments=frozenset({"limit"}),
                ),
                ToolPolicy(
                    tool_name=GOOGLE_CALENDAR_EVENT_CREATE_TOOL,
                    scope=ActionScope.WRITE,
                    risk=RiskLevel.HIGH,
                    allowed_targets=frozenset({"primary"}),
                    required_arguments=frozenset(
                        {"summary", "start", "end", "time_zone"}
                    ),
                ),
                ToolPolicy(
                    tool_name=GOOGLE_CALENDAR_EVENT_UPDATE_TOOL,
                    scope=ActionScope.WRITE,
                    risk=RiskLevel.HIGH,
                    allowed_targets=frozenset({"primary"}),
                    required_arguments=frozenset({"event_id"}),
                    optional_arguments=frozenset(
                        {"summary", "start", "end", "time_zone"}
                    ),
                ),
                ToolPolicy(
                    tool_name=GOOGLE_CALENDAR_EVENT_DELETE_TOOL,
                    scope=ActionScope.WRITE,
                    risk=RiskLevel.HIGH,
                    allowed_targets=frozenset({"primary"}),
                    required_arguments=frozenset({"event_id"}),
                ),
            )
        )
    return PolicyEngine(policies, async_permission_service=async_permission_service)
