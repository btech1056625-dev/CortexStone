"""Authenticated Google Calendar event API using policy-controlled executions."""

import hashlib
import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.dependencies import (
    get_approval_service,
    get_authenticated_user,
    get_google_calendar_tool_runner,
    get_policy_principal,
)
from cortexstone.security.approvals.service import SqlAlchemyApprovalService
from cortexstone.security.policy import PolicyPrincipal, PolicyStatus
from cortexstone.tools.connectors.google_calendar import (
    GOOGLE_CALENDAR_EVENT_CREATE_TOOL,
    GOOGLE_CALENDAR_EVENT_DELETE_TOOL,
    GOOGLE_CALENDAR_EVENT_READ_TOOL,
    GOOGLE_CALENDAR_EVENT_UPDATE_TOOL,
    GoogleCalendarConflictError,
    GoogleCalendarEvent,
    GoogleCalendarEventNotFoundError,
    GoogleCalendarProviderError,
)
from cortexstone.tools.runner import ToolExecutionDenied, ToolNotRegisteredError, ToolRunner

router = APIRouter(prefix="/google-calendar", tags=["google-calendar"])
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class EventCreateRequest(BaseModel):
    """Fields required to create a timed event on the caller's primary calendar."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    start: AwareDatetime
    end: AwareDatetime
    time_zone: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_event_range(self) -> "EventCreateRequest":
        if self.end <= self.start:
            raise ValueError("Event end must be after its start.")
        return self


class EventUpdateRequest(BaseModel):
    """A bounded partial update for an existing timed Calendar event."""

    model_config = ConfigDict(extra="forbid")

    summary: str | None = Field(default=None, min_length=1, max_length=500)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    time_zone: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_update(self) -> "EventUpdateRequest":
        fields = self.model_fields_set
        if not fields:
            raise ValueError("At least one event field must be provided.")
        if all(getattr(self, field) is None for field in fields):
            raise ValueError("At least one event field must have a value.")
        if ("start" in fields) != ("end" in fields):
            raise ValueError("Both start and end are required when changing event times.")
        if {"start", "end"}.issubset(fields) and "time_zone" not in fields:
            raise ValueError("A time zone is required when changing event times.")
        if "start" in fields and self.end is not None and self.start is not None:
            if self.end <= self.start:
                raise ValueError("Event end must be after its start.")
        if "time_zone" in fields and not {"start", "end"}.issubset(fields):
            raise ValueError("A time zone can only be changed with event times.")
        return self


@router.get("/events", response_model=list[GoogleCalendarEvent])
async def list_events(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    principal: Annotated[PolicyPrincipal, Depends(get_policy_principal)],
    tool_runner: Annotated[ToolRunner, Depends(get_google_calendar_tool_runner)],
    time_min: Annotated[AwareDatetime, Query(alias="start")],
    time_max: Annotated[AwareDatetime, Query(alias="end")],
    time_zone: Annotated[str, Query(min_length=1, max_length=64)] = "Asia/Kolkata",
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[GoogleCalendarEvent]:
    action = ProposedAction(
        tool_name=GOOGLE_CALENDAR_EVENT_READ_TOOL,
        target_ref="primary",
        arguments={
            "time_min": time_min.isoformat(),
            "time_max": time_max.isoformat(),
            "time_zone": time_zone,
            "limit": limit,
        },
        purpose="List events in the connected primary calendar.",
    )
    result = await _execute(action, user, principal, tool_runner)
    if not isinstance(result, tuple) or any(
        not isinstance(event, GoogleCalendarEvent) for event in result
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google Calendar returned an invalid event list.",
        )
    return list(result)


@router.post("/events", response_model=None, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreateRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    principal: Annotated[PolicyPrincipal, Depends(get_policy_principal)],
    tool_runner: Annotated[ToolRunner, Depends(get_google_calendar_tool_runner)],
    approval_service: Annotated[SqlAlchemyApprovalService, Depends(get_approval_service)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ],
) -> GoogleCalendarEvent | Response:
    _validate_idempotency_key(idempotency_key)
    action = ProposedAction(
        tool_name=GOOGLE_CALENDAR_EVENT_CREATE_TOOL,
        target_ref="primary",
        arguments={
            "summary": payload.summary.strip(),
            "start": payload.start.isoformat(),
            "end": payload.end.isoformat(),
            "time_zone": payload.time_zone,
        },
        purpose="Create an event in the connected primary calendar.",
        idempotency_key=_principal_idempotency_key(user.subject, idempotency_key),
    )
    result = await _execute_write(
        action, user, principal, tool_runner, approval_service
    )
    return result if isinstance(result, Response) else _require_event(result)


@router.patch("/events/{event_id}", response_model=None)
async def update_event(
    payload: EventUpdateRequest,
    event_id: Annotated[str, Path(min_length=1, max_length=256)],
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    principal: Annotated[PolicyPrincipal, Depends(get_policy_principal)],
    tool_runner: Annotated[ToolRunner, Depends(get_google_calendar_tool_runner)],
    approval_service: Annotated[SqlAlchemyApprovalService, Depends(get_approval_service)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ],
) -> GoogleCalendarEvent | Response:
    _validate_idempotency_key(idempotency_key)
    arguments: dict[str, object] = {"event_id": event_id}
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if isinstance(value, datetime):
            arguments[field] = value.isoformat()
        elif value is not None:
            arguments[field] = value.strip() if field == "summary" else value
    action = ProposedAction(
        tool_name=GOOGLE_CALENDAR_EVENT_UPDATE_TOOL,
        target_ref="primary",
        arguments=arguments,
        purpose="Update an event in the connected primary calendar.",
        idempotency_key=_principal_idempotency_key(user.subject, idempotency_key),
    )
    result = await _execute_write(
        action, user, principal, tool_runner, approval_service
    )
    return result if isinstance(result, Response) else _require_event(result)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: Annotated[str, Path(min_length=1, max_length=256)],
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    principal: Annotated[PolicyPrincipal, Depends(get_policy_principal)],
    tool_runner: Annotated[ToolRunner, Depends(get_google_calendar_tool_runner)],
    approval_service: Annotated[SqlAlchemyApprovalService, Depends(get_approval_service)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ],
) -> Response:
    _validate_idempotency_key(idempotency_key)
    action = ProposedAction(
        tool_name=GOOGLE_CALENDAR_EVENT_DELETE_TOOL,
        target_ref="primary",
        arguments={"event_id": event_id},
        purpose="Delete an event from the connected primary calendar.",
        idempotency_key=_principal_idempotency_key(user.subject, idempotency_key),
    )
    result = await _execute_write(
        action, user, principal, tool_runner, approval_service
    )
    if isinstance(result, Response):
        return result
    if not isinstance(result, dict) or result.get("deleted") is not True:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google Calendar returned an invalid deletion result.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _execute_write(
    action: ProposedAction,
    user: AuthenticatedUser,
    principal: PolicyPrincipal,
    tool_runner: ToolRunner,
    approval_service: SqlAlchemyApprovalService,
) -> GoogleCalendarEvent | dict[str, bool] | Response:
    try:
        return await _execute(action, user, principal, tool_runner)
    except ToolExecutionDenied as exc:
        if exc.decision.status != PolicyStatus.REQUIRE_APPROVAL:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Google Calendar action is not permitted.",
            ) from None
        approval = await approval_service.create(owner_id=user.subject, action=action)
        return JSONResponse(
            content={
                "status": "approval_required",
                "approval_id": str(approval.id),
                "expires_at": approval.expires_at.isoformat(),
            },
            status_code=status.HTTP_202_ACCEPTED,
            media_type="application/json",
            headers={"Location": f"/api/v1/approvals/{approval.id}"},
        )


async def _execute(
    action: ProposedAction,
    user: AuthenticatedUser,
    principal: PolicyPrincipal,
    tool_runner: ToolRunner,
) -> object:
    if principal.principal_id != user.subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated principal could not be resolved.",
        )
    try:
        return await tool_runner.execute(principal, action)
    except ToolExecutionDenied:
        raise
    except ToolNotRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Connect a Google account with Calendar event access.",
        ) from None
    except GoogleCalendarEventNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google Calendar event not found.",
        ) from None
    except GoogleCalendarConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Google Calendar event conflicts with an existing operation.",
        ) from None
    except GoogleCalendarProviderError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google Calendar could not complete the request.",
        ) from None


def _require_event(result: object) -> GoogleCalendarEvent:
    if not isinstance(result, GoogleCalendarEvent):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google Calendar returned an invalid event.",
        )
    return result


def _validate_idempotency_key(value: str) -> None:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The idempotency key is invalid.",
        )


def _principal_idempotency_key(principal_id: str, key: str) -> str:
    return hashlib.sha256(f"{principal_id}:{key}".encode()).hexdigest()
