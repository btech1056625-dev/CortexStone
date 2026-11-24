"""Owner-scoped action approval request and decision endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.dependencies import (
    get_approval_service,
    get_authenticated_user,
    get_policy_engine,
    get_policy_principal,
)
from cortexstone.api.v1.schemas import (
    ApprovalCreateRequest,
    ApprovalDecisionRequest,
    ApprovalResponse,
)
from cortexstone.security.approvals.service import (
    ApprovalConflictError,
    ApprovalStatus,
    SqlAlchemyApprovalService,
)
from cortexstone.security.policy import PolicyEngine, PolicyPrincipal, PolicyStatus

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post("", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def request_approval(
    payload: ApprovalCreateRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    principal: Annotated[PolicyPrincipal, Depends(get_policy_principal)],
    policy_engine: Annotated[PolicyEngine, Depends(get_policy_engine)],
    approval_service: Annotated[SqlAlchemyApprovalService, Depends(get_approval_service)],
) -> ApprovalResponse:
    """Persist an approval request only when policy requires human approval."""
    if principal.principal_id != user.subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated principal could not be resolved.",
        )
    decision = await policy_engine.evaluate_async(principal, payload.action)
    if decision.status == PolicyStatus.DENY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The action is not permitted by current policy.",
        )
    if decision.status != PolicyStatus.REQUIRE_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This action does not require approval.",
        )

    record = await approval_service.create(owner_id=user.subject, action=payload.action)
    return ApprovalResponse.from_record(record)


@router.get("", response_model=list[ApprovalResponse])
async def list_approvals(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    approval_service: Annotated[SqlAlchemyApprovalService, Depends(get_approval_service)],
) -> list[ApprovalResponse]:
    """List approval requests belonging only to the verified principal."""
    records = await approval_service.list_for_owner(user.subject)
    return [ApprovalResponse.from_record(record) for record in records]


@router.post("/{approval_id}/decision", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    approval_service: Annotated[SqlAlchemyApprovalService, Depends(get_approval_service)],
) -> ApprovalResponse:
    """Record the owning principal's decision on a pending approval."""
    try:
        record = await approval_service.decide(
            approval_id,
            owner_id=user.subject,
            decision=ApprovalStatus(payload.decision),
        )
    except ApprovalConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")
    return ApprovalResponse.from_record(record)


@router.delete("/{approval_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_approval(
    approval_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    approval_service: Annotated[SqlAlchemyApprovalService, Depends(get_approval_service)],
) -> Response:
    """Revoke a pending or approved request belonging to the caller."""
    try:
        record = await approval_service.revoke(approval_id, owner_id=user.subject)
    except ApprovalConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
