"""Tests for authenticated, owner-scoped approval request APIs."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.config import Settings
from cortexstone.api.dependencies import (
    get_approval_service,
    get_authenticated_user,
    get_policy_engine,
    get_policy_principal,
)
from cortexstone.api.main import create_app
from cortexstone.security.approvals.service import ApprovalRecord, ApprovalStatus
from cortexstone.security.policy import (
    ActionScope,
    PermissionGrant,
    PolicyEngine,
    PolicyPrincipal,
    RiskLevel,
    ToolPolicy,
)

OWNER = "approval-owner"
ACTION = ProposedAction(
    tool_name="notes.create",
    target_ref="notes/personal",
    arguments={"title": "Plan", "content": "Review"},
    purpose="Create the requested note",
)


class InMemoryApprovalService:
    def __init__(self) -> None:
        self.records: dict[UUID, ApprovalRecord] = {}
        self.created_actions: list[ProposedAction] = []

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
        self.created_actions.append(action)
        return record

    async def list_for_owner(self, owner_id: str) -> tuple[ApprovalRecord, ...]:
        return tuple(record for record in self.records.values() if record.owner_id == owner_id)

    async def decide(self, approval_id, *, owner_id: str, decision: ApprovalStatus):
        record = self.records.get(approval_id)
        if record is None or record.owner_id != owner_id:
            return None
        updated = ApprovalRecord(
            id=record.id,
            owner_id=record.owner_id,
            action=record.action,
            action_hash=record.action_hash,
            status=decision,
            expires_at=record.expires_at,
            created_at=record.created_at,
            decided_at=datetime.now(UTC),
            decided_by=owner_id,
        )
        self.records[approval_id] = updated
        return updated

    async def revoke(self, approval_id, *, owner_id: str):
        record = self.records.get(approval_id)
        if record is None or record.owner_id != owner_id:
            return None
        updated = ApprovalRecord(
            id=record.id,
            owner_id=record.owner_id,
            action=record.action,
            action_hash=record.action_hash,
            status=ApprovalStatus.REVOKED,
            expires_at=record.expires_at,
            created_at=record.created_at,
            decided_at=datetime.now(UTC),
            decided_by=owner_id,
        )
        self.records[approval_id] = updated
        return updated


def make_app(*, owner_id: str = OWNER, permitted: bool = True):
    application = create_app(Settings())
    service = InMemoryApprovalService()
    principal = PolicyPrincipal(
        principal_id=owner_id,
        grants=(
            (
                PermissionGrant(
                    tool_name="notes.create",
                    scope=ActionScope.WRITE,
                    allowed_targets=frozenset({"notes/personal"}),
                ),
            )
            if permitted
            else ()
        ),
    )
    policy_engine = PolicyEngine(
        [
            ToolPolicy(
                tool_name="notes.create",
                scope=ActionScope.WRITE,
                risk=RiskLevel.LOW,
                allowed_targets=frozenset({"notes/personal"}),
                required_arguments=frozenset({"title", "content"}),
            )
        ]
    )
    application.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        subject=owner_id,
        display_name=owner_id,
    )
    application.dependency_overrides[get_policy_principal] = lambda: principal
    application.dependency_overrides[get_policy_engine] = lambda: policy_engine
    application.dependency_overrides[get_approval_service] = lambda: service
    return application, service


def request(application, method: str, path: str, payload: dict | None = None):
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, json=payload)

    return asyncio.run(send())


def test_approval_request_is_persisted_and_only_listed_for_owner():
    application, service = make_app()
    created = request(
        application,
        "POST",
        "/api/v1/approvals",
        {"action": ACTION.model_dump(mode="json")},
    )

    assert created.status_code == 201
    body = created.json()
    assert body["owner_id"] == OWNER
    assert body["status"] == "pending"
    assert body["action"]["tool_name"] == ACTION.tool_name
    assert body["action_hash"] == PolicyEngine.action_hash(ACTION)
    assert service.created_actions == [ACTION]

    listed = request(application, "GET", "/api/v1/approvals")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]


def test_approval_request_is_denied_without_current_permission():
    application, service = make_app(permitted=False)

    response = request(
        application,
        "POST",
        "/api/v1/approvals",
        {"action": ACTION.model_dump(mode="json")},
    )

    assert response.status_code == 403
    assert service.created_actions == []


def test_only_owner_can_decide_or_revoke_approval():
    application, service = make_app()
    created = request(
        application,
        "POST",
        "/api/v1/approvals",
        {"action": ACTION.model_dump(mode="json")},
    )
    approval_id = created.json()["id"]

    decision = request(
        application,
        "POST",
        f"/api/v1/approvals/{approval_id}/decision",
        {"decision": "approved"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"
    assert decision.json()["decided_by"] == OWNER

    application.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        subject="different-user",
        display_name="different-user",
    )
    hidden = request(
        application, "POST", f"/api/v1/approvals/{approval_id}/decision", {"decision": "rejected"}
    )
    assert hidden.status_code == 404
    assert service.records[UUID(approval_id)].status == ApprovalStatus.APPROVED
