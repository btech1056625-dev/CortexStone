"""Version 1 and operational health routes."""

import logging
import os
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from cortexstone.api.dependencies import get_policy_engine, get_policy_principal
from cortexstone.api.v1.schemas import ActionValidationRequest, ActionValidationResponse
from cortexstone.security.policy import PolicyEngine, PolicyPrincipal

logger = logging.getLogger(__name__)

router = APIRouter()
operational_router = APIRouter(tags=["health"])


@router.get("/health", tags=["health"])
def versioned_health() -> dict[str, str]:
    return {"status": "ok", "api_version": "v1"}


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


@operational_router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@operational_router.get("/health/ready")
def readiness(request: Request) -> dict[str, str]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error(
            "Readiness check failed: DATABASE_URL is not configured",
            extra={"request_id": request.state.request_id},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "dependency": "database"},
        )

    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
    except psycopg.Error as exc:
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
