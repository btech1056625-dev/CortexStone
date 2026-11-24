"""Admin-only endpoints for granting and revoking tool permissions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.dependencies import (
    get_authenticated_user,
    get_permission_service,
    get_policy_engine,
)
from cortexstone.api.v1.schemas import (
    PermissionGrantCreateRequest,
    PermissionGrantResponse,
    PrincipalRevocationResponse,
)
from cortexstone.security.permissions.service import SqlAlchemyPermissionService
from cortexstone.security.policy import PolicyEngine

router = APIRouter(prefix="/admin/permissions", tags=["permissions"])


def require_permission_admin(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> AuthenticatedUser:
    """Require a verified subject explicitly configured as a permission administrator."""
    settings = request.app.state.settings
    if user.subject not in settings.permission_admin_subjects:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission administrator access required.",
        )
    return user


@router.post("", response_model=PermissionGrantResponse, status_code=status.HTTP_201_CREATED)
async def grant_permission(
    payload: PermissionGrantCreateRequest,
    actor: Annotated[AuthenticatedUser, Depends(require_permission_admin)],
    response: Response,
    permission_service: Annotated[SqlAlchemyPermissionService, Depends(get_permission_service)],
    policy_engine: Annotated[PolicyEngine, Depends(get_policy_engine)],
) -> PermissionGrantResponse:
    """Grant an exact subset of the configured server policy's targets."""
    tool_policy = policy_engine.get_tool_policy(payload.tool_name)
    if (
        tool_policy is None
        or payload.scope != tool_policy.scope
        or not set(payload.allowed_targets).issubset(tool_policy.allowed_targets)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Grant must match a registered tool policy and its allowed targets.",
        )

    record, created = await permission_service.grant(
        principal_id=payload.principal_id,
        tool_name=payload.tool_name,
        scope=payload.scope,
        allowed_targets=payload.allowed_targets,
        actor_id=actor.subject,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return PermissionGrantResponse.from_record(record)


@router.get("/{principal_id}", response_model=list[PermissionGrantResponse])
async def list_principal_permissions(
    principal_id: str,
    _: Annotated[AuthenticatedUser, Depends(require_permission_admin)],
    permission_service: Annotated[SqlAlchemyPermissionService, Depends(get_permission_service)],
) -> list[PermissionGrantResponse]:
    """List current and historical grants for an administrator's access review."""
    records = await permission_service.list_grants(principal_id)
    return [PermissionGrantResponse.from_record(record) for record in records]


@router.delete("/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_permission(
    grant_id: UUID,
    actor: Annotated[AuthenticatedUser, Depends(require_permission_admin)],
    permission_service: Annotated[SqlAlchemyPermissionService, Depends(get_permission_service)],
) -> Response:
    """Revoke one grant; repeated revocation returns 404 and changes nothing."""
    record = await permission_service.revoke(grant_id, actor_id=actor.subject)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/principals/{principal_id}",
    response_model=PrincipalRevocationResponse,
)
async def revoke_principal_permissions(
    principal_id: str,
    actor: Annotated[AuthenticatedUser, Depends(require_permission_admin)],
    permission_service: Annotated[SqlAlchemyPermissionService, Depends(get_permission_service)],
) -> PrincipalRevocationResponse:
    """Immediately revoke every active grant for an offboarded or changed principal."""
    revoked_count = await permission_service.revoke_principal(
        principal_id,
        actor_id=actor.subject,
    )
    return PrincipalRevocationResponse(
        principal_id=principal_id,
        revoked_count=revoked_count,
    )
