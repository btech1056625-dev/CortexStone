"""Version 1 and operational health routes."""

import logging
from pathlib import Path
from typing import Annotated

from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.dependencies import (
    get_authenticated_user,
    get_policy_engine,
    get_policy_principal,
)
from cortexstone.api.v1.schemas import (
    ActionValidationRequest,
    ActionValidationResponse,
    CurrentUserResponse,
)
from cortexstone.security.policy import PolicyEngine, PolicyPrincipal

logger = logging.getLogger(__name__)

MIGRATION_DIRECTORY = Path(__file__).resolve().parents[2] / "db" / "migrations"
MIGRATION_HEADS = frozenset(ScriptDirectory(str(MIGRATION_DIRECTORY)).get_heads())

router = APIRouter()
operational_router = APIRouter(tags=["health"])


@router.get("/health", tags=["health"], include_in_schema=False)
def versioned_health() -> dict[str, str]:
    return {"status": "ok", "api_version": "v1"}


@router.get("/me", response_model=CurrentUserResponse, tags=["users"])
def current_user(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> CurrentUserResponse:
    """Return the subject established by verified bearer-token claims."""
    return CurrentUserResponse(id=user.subject, display_name=user.display_name)


@router.post(
    "/actions/validate",
    response_model=ActionValidationResponse,
    tags=["actions"],
)
async def validate_proposed_action(
    request: ActionValidationRequest,
    policy_engine: Annotated[PolicyEngine, Depends(get_policy_engine)],
    principal: Annotated[PolicyPrincipal, Depends(get_policy_principal)],
) -> ActionValidationResponse:
    decision = await policy_engine.evaluate_async(principal, request.action)
    return ActionValidationResponse.from_decision(decision)


@operational_router.get("/health")
@operational_router.get("/health/live", include_in_schema=False)
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@operational_router.get("/ready")
@operational_router.get("/health/ready", include_in_schema=False)
async def readiness(request: Request) -> dict[str, str]:
    engine = request.app.state.db_engine
    if engine is None:
        logger.error(
            "Readiness check failed: DATABASE_URL is not configured",
            extra={"request_id": request.state.request_id},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "dependency": "database"},
        )

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.error(
            "Database readiness check failed (%s)",
            type(exc).__name__,
            extra={"request_id": request.state.request_id},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "dependency": "database"},
        ) from None

    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            applied_heads = frozenset(result.scalars().all())
    except SQLAlchemyError as exc:
        logger.error(
            "Migration readiness check failed (%s)",
            type(exc).__name__,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "dependency": "migrations"},
        ) from None

    if applied_heads != MIGRATION_HEADS:
        logger.error(
            "Migration readiness check failed: applied migrations are not at head",
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "dependency": "migrations"},
        )

    return {"status": "ok"}
