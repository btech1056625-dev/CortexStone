"""Version 1 and operational health routes."""

import logging
from typing import Annotated

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
def validate_proposed_action(
    request: ActionValidationRequest,
    policy_engine: Annotated[PolicyEngine, Depends(get_policy_engine)],
    principal: Annotated[PolicyPrincipal, Depends(get_policy_principal)],
) -> ActionValidationResponse:
    decision = policy_engine.evaluate(principal, request.action)
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

    return {"status": "ok"}
