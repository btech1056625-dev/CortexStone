"""Tests for authenticated and policy-gated Calendar event routes."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.config import Settings
from cortexstone.api.dependencies import (
    build_policy_engine,
    get_approval_service,
    get_authenticated_user,
    get_google_calendar_tool_runner,
    get_policy_principal,
)
from cortexstone.api.main import create_app
from cortexstone.security.action_runs import ActionRunStatus
from cortexstone.security.approvals.service import ApprovalRecord, ApprovalStatus
from cortexstone.security.policy import (
    ActionScope,
    ApprovalEvidence,
    PermissionGrant,
    PolicyEngine,
    PolicyPrincipal,
)
from cortexstone.tools.connectors.google_calendar import (
    GOOGLE_CALENDAR_EVENT_CREATE_TOOL,
    GOOGLE_CALENDAR_EVENT_DELETE_TOOL,
    GOOGLE_CALENDAR_EVENT_READ_TOOL,
    GOOGLE_CALENDAR_EVENT_UPDATE_TOOL,
    GoogleCalendarEvent,
)
from cortexstone.tools.runner import ToolRunner

OWNER = "calendar-user"
EVENT = GoogleCalendarEvent(
    id="event123",
    summary="Planning",
    start="2026-10-30T09:00:00+05:30",
    end="2026-10-30T10:00:00+05:30",
    timezone="Asia/Kolkata",
)


class InMemoryRunRecorder:
    def __init__(self) -> None:
        self.transitions: list[ActionRunStatus] = []

    async def create_attempt(self, _principal_id: str, _action: ProposedAction) -> UUID:
        return uuid4()

    async def transition(self, _run_id: UUID, status: ActionRunStatus, **_kwargs) -> None:
        self.transitions.append(status)


class InMemoryApprovalService:
    def __init__(self) -> None:
        self.records: dict[UUID, ApprovalRecord] = {}

    async def create(self, *, owner_id: str, action: ProposedAction) -> ApprovalRecord:
        now = datetime.now(UTC)
        record = ApprovalRecord(
            id=uuid4(),
            owner_id=owner_id,
            action=action,
            action_hash=PolicyEngine.action_hash(action),
            status=ApprovalStatus.PENDING,
            expires_at=now + timedelta(minutes=15),
            created_at=now,
            decided_at=None,
            decided_by=None,
        )
        self.records[record.id] = record
        return record

    async def decide(self, approval_id, *, owner_id: str, decision: ApprovalStatus):
        record = self.records.get(approval_id)
        if record is None or record.owner_id != owner_id:
            return None
        updated = replace(
            record,
            status=decision,
            decided_at=datetime.now(UTC),
            decided_by=owner_id,
        )
        self.records[approval_id] = updated
        return updated

    async def resolve_for_action(self, principal: PolicyPrincipal, action: ProposedAction):
        action_hash = PolicyEngine.action_hash(action)
        for approval_id, record in tuple(self.records.items()):
            if (
                record.owner_id == principal.principal_id
                and record.action_hash == action_hash
                and record.status == ApprovalStatus.APPROVED
            ):
                self.records[approval_id] = replace(
                    record,
                    status=ApprovalStatus.CONSUMED,
                    decided_at=datetime.now(UTC),
                    decided_by=principal.principal_id,
                )
                return ApprovalEvidence(
                    approved=True,
                    action_hash=action_hash,
                    target_ref=action.target_ref,
                    expires_at=record.expires_at,
                    principal_id=principal.principal_id,
                )
        return None


def make_calendar_app():
    application = create_app(Settings())
    approvals = InMemoryApprovalService()
    recorder = InMemoryRunRecorder()
    provider_actions: list[ProposedAction] = []

    async def execute(action: ProposedAction):
        provider_actions.append(action)
        if action.tool_name == GOOGLE_CALENDAR_EVENT_READ_TOOL:
            return (EVENT,)
        if action.tool_name == GOOGLE_CALENDAR_EVENT_DELETE_TOOL:
            return {"deleted": True}
        return EVENT

    tools = (
        GOOGLE_CALENDAR_EVENT_READ_TOOL,
        GOOGLE_CALENDAR_EVENT_CREATE_TOOL,
        GOOGLE_CALENDAR_EVENT_UPDATE_TOOL,
        GOOGLE_CALENDAR_EVENT_DELETE_TOOL,
    )
    engine = build_policy_engine((), google_calendar_enabled=True)
    runner = ToolRunner(
        engine,
        {tool: execute for tool in tools},
        run_recorder=recorder,
        approval_resolver=approvals.resolve_for_action,
    )
    application.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        subject=OWNER,
        display_name="Calendar User",
    )
    application.dependency_overrides[get_policy_principal] = lambda: PolicyPrincipal(
        principal_id=OWNER,
        grants=tuple(
            PermissionGrant(
                tool_name=tool,
                scope=(
                    ActionScope.READ
                    if tool == GOOGLE_CALENDAR_EVENT_READ_TOOL
                    else ActionScope.WRITE
                ),
                allowed_targets=frozenset({"primary"}),
            )
            for tool in tools
        ),
    )
    application.dependency_overrides[get_google_calendar_tool_runner] = lambda: runner
    application.dependency_overrides[get_approval_service] = lambda: approvals
    return application, approvals, provider_actions


def request(application, method: str, path: str, payload=None, *, headers=None):
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, json=payload, headers=headers)

    return asyncio.run(send())


def test_calendar_read_route_dispatches_through_policy_runner():
    application, _approvals, provider_actions = make_calendar_app()

    response = request(
        application,
        "GET",
        "/api/v1/google-calendar/events?start=2026-10-30T00:00:00%2B05:30"
        "&end=2026-10-31T00:00:00%2B05:30&time_zone=Asia%2FKolkata",
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == EVENT.id
    assert provider_actions[0].tool_name == GOOGLE_CALENDAR_EVENT_READ_TOOL
    assert provider_actions[0].target_ref == "primary"


def test_calendar_write_requires_and_consumes_one_time_approval():
    application, approvals, provider_actions = make_calendar_app()
    payload = {
        "summary": "Planning",
        "start": "2026-10-30T09:00:00+05:30",
        "end": "2026-10-30T10:00:00+05:30",
        "time_zone": "Asia/Kolkata",
    }
    headers = {"Idempotency-Key": "create-event-1"}

    pending = request(
        application,
        "POST",
        "/api/v1/google-calendar/events",
        payload,
        headers=headers,
    )

    assert pending.status_code == 202
    assert pending.json()["status"] == "approval_required"
    approval_id = UUID(pending.json()["approval_id"])
    assert provider_actions == []

    decision = request(
        application,
        "POST",
        f"/api/v1/approvals/{approval_id}/decision",
        {"decision": "approved"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"

    executed = request(
        application,
        "POST",
        "/api/v1/google-calendar/events",
        payload,
        headers=headers,
    )
    assert executed.status_code == 201
    assert executed.json()["id"] == EVENT.id
    assert len(provider_actions) == 1
    assert approvals.records[approval_id].status == ApprovalStatus.CONSUMED

    replay = request(
        application,
        "POST",
        "/api/v1/google-calendar/events",
        payload,
        headers=headers,
    )
    assert replay.status_code == 202
    assert len(provider_actions) == 1


def test_calendar_write_rejects_invalid_idempotency_key():
    application, _approvals, provider_actions = make_calendar_app()

    response = request(
        application,
        "POST",
        "/api/v1/google-calendar/events",
        {
            "summary": "Planning",
            "start": "2026-10-30T09:00:00+05:30",
            "end": "2026-10-30T10:00:00+05:30",
            "time_zone": "Asia/Kolkata",
        },
        headers={"Idempotency-Key": "not valid"},
    )

    assert response.status_code == 422
    assert provider_actions == []
