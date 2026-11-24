"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from cortexstone.agent.models.interface import ModelError, ModelSchemaValidationError
from cortexstone.agent.models.split import SplitModelClient
from cortexstone.api.auth import OIDCAuthenticator
from cortexstone.api.config import Settings
from cortexstone.api.dependencies import build_policy_engine
from cortexstone.api.v1.approvals import router as approvals_router
from cortexstone.api.v1.chat import router as chat_router
from cortexstone.api.v1.github import router as github_router
from cortexstone.api.v1.memories import router as memory_router
from cortexstone.api.v1.permissions import router as permissions_router
from cortexstone.api.v1.router import operational_router
from cortexstone.api.v1.router import router as v1_router
from cortexstone.db.session import create_engine_from_url, create_session_factory
from cortexstone.memory.embeddings.bge import BGEEmbeddingProvider
from cortexstone.memory.embeddings.config import EmbeddingError
from cortexstone.security.action_runs.service import SqlAlchemyActionRunService
from cortexstone.security.approvals.service import SqlAlchemyApprovalService
from cortexstone.security.permissions.service import SqlAlchemyPermissionService
from cortexstone.security.redaction import configure_redacting_logging
from cortexstone.tools.connectors.github import GITHUB_ISSUE_READ_TOOL, GitHubIssueReader
from cortexstone.tools.runner import ToolExecutor

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the API with validated settings and application-scoped services."""
    configure_redacting_logging()
    configured_settings = settings or Settings.from_environment()

    engine: AsyncEngine | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    if configured_settings.database_url is not None:
        engine = create_engine_from_url(configured_settings.database_url)
        session_factory = create_session_factory(engine)

    authenticator = None
    if (
        configured_settings.auth_issuer is not None
        and configured_settings.auth_audience is not None
        and configured_settings.auth_jwks_url is not None
    ):
        authenticator = OIDCAuthenticator(
            issuer=configured_settings.auth_issuer,
            audience=configured_settings.auth_audience,
            jwks_url=configured_settings.auth_jwks_url,
        )

    github_http_client: httpx.AsyncClient | None = None
    github_issue_reader: GitHubIssueReader | None = None
    tool_executors: dict[str, ToolExecutor] = {}
    if (
        configured_settings.github_token is not None
        and configured_settings.github_issue_read_allowed_targets
    ):
        github_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            follow_redirects=False,
        )
        github_issue_reader = GitHubIssueReader(
            token=configured_settings.github_token,
            allowed_repositories=configured_settings.github_issue_read_allowed_targets,
            client=github_http_client,
        )
        tool_executors[GITHUB_ISSUE_READ_TOOL] = github_issue_reader

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if github_http_client is not None:
                await github_http_client.aclose()
            if engine is not None:
                await engine.dispose()

    application = FastAPI(
        title="Cortexstone API",
        description="Cortexstone backend API.",
        version="0.1.0",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.settings = configured_settings
    application.state.db_engine = engine
    application.state.db_session_factory = session_factory
    application.state.authenticator = authenticator
    application.state.github_http_client = github_http_client
    application.state.github_issue_reader = github_issue_reader
    application.state.tool_executors = tool_executors
    application.state.memory_embedding_provider = BGEEmbeddingProvider()
    application.state.model_client = (
        SplitModelClient(
            groq_api_key=configured_settings.groq_api_key,
            groq_model_id=configured_settings.groq_router_model_id,
            google_api_key=configured_settings.google_api_key,
            google_model_id=configured_settings.google_reasoner_model_id,
            groq_base_url=configured_settings.groq_base_url,
            google_base_url=configured_settings.google_base_url,
        )
        if configured_settings.groq_api_key is not None
        else None
    )
    permission_service = (
        SqlAlchemyPermissionService(session_factory) if session_factory is not None else None
    )
    approval_service = (
        SqlAlchemyApprovalService(session_factory) if session_factory is not None else None
    )
    action_run_service = (
        SqlAlchemyActionRunService(session_factory) if session_factory is not None else None
    )
    application.state.permission_service = permission_service
    application.state.approval_service = approval_service
    application.state.action_run_service = action_run_service
    application.state.policy_engine = build_policy_engine(
        configured_settings.notes_search_allowed_targets,
        github_issue_read_allowed_targets=(
            configured_settings.github_issue_read_allowed_targets
        ),
        github_enabled=configured_settings.github_token is not None,
        async_permission_service=permission_service,
    )

    if configured_settings.cors_allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(configured_settings.cors_allowed_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
        )

    @application.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    application.include_router(operational_router)
    application.include_router(v1_router, prefix="/api/v1")
    application.include_router(chat_router, prefix="/api/v1")
    application.include_router(memory_router, prefix="/api/v1")
    application.include_router(github_router, prefix="/api/v1")
    application.include_router(permissions_router, prefix="/api/v1")
    application.include_router(approvals_router, prefix="/api/v1")

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code_by_status = {
            404: "not_found",
            401: "unauthorized",
            403: "forbidden",
            409: "conflict",
            502: "invalid_model_response",
            422: "invalid_request",
            503: "service_unavailable",
        }
        code = code_by_status.get(exc.status_code, "http_error")
        message = (
            exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        )
        return _error_response(request, exc.status_code, code, message, headers=exc.headers)

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(request, 422, "invalid_request", "Request validation failed.")

    @application.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error(
            "Database operation failed (%s)",
            type(exc).__name__,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return _error_response(
            request,
            503,
            "service_unavailable",
            "The database is temporarily unavailable.",
        )

    @application.exception_handler(ModelError)
    async def handle_model_error(request: Request, exc: ModelError) -> JSONResponse:
        logger.error(
            "Model operation failed (%s)",
            type(exc).__name__,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return _error_response(
            request,
            503,
            "service_unavailable",
            "The model provider is temporarily unavailable.",
        )

    @application.exception_handler(ModelSchemaValidationError)
    async def handle_invalid_model_response(
        request: Request,
        exc: ModelSchemaValidationError,
    ) -> JSONResponse:
        logger.warning(
            "Model response validation failed",
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return _error_response(
            request,
            502,
            "invalid_model_response",
            "The model returned an invalid response.",
        )

    @application.exception_handler(EmbeddingError)
    async def handle_embedding_error(request: Request, exc: EmbeddingError) -> JSONResponse:
        logger.error(
            "Embedding operation failed (%s)",
            type(exc).__name__,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return _error_response(
            request,
            503,
            "service_unavailable",
            "Memory retrieval is temporarily unavailable.",
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled request error (%s)",
            type(exc).__name__,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return _error_response(
            request,
            500,
            "internal_server_error",
            "An unexpected error occurred.",
        )

    return application


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    response_headers = dict(headers or {})
    if request_id:
        response_headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status_code,
        headers=response_headers or None,
        content={
            "error": {"code": code, "message": message},
            "request_id": request_id,
        },
    )


app = create_app()
