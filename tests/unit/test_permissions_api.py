import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.config import Settings
from cortexstone.api.dependencies import get_authenticated_user, get_permission_service
from cortexstone.api.main import create_app
from cortexstone.security.permissions.service import PermissionGrantRecord
from cortexstone.security.policy import ActionScope


class InMemoryPermissionService:
    def __init__(self) -> None:
        self.records: dict[str, list[PermissionGrantRecord]] = {}
        self.audit_events: list[tuple[str, str, str]] = []

    async def grant(
        self,
        *,
        principal_id: str,
        tool_name: str,
        scope: ActionScope,
        allowed_targets: tuple[str, ...],
        actor_id: str,
    ) -> tuple[PermissionGrantRecord, bool]:
        existing = next(
            (
                record
                for record in self.records.get(principal_id, ())
                if record.revoked_at is None
                and record.tool_name == tool_name
                and record.scope == scope
                and record.allowed_targets == allowed_targets
            ),
            None,
        )
        if existing is not None:
            return existing, False
        record = PermissionGrantRecord(
            id=uuid4(),
            principal_id=principal_id,
            tool_name=tool_name,
            scope=scope,
            allowed_targets=allowed_targets,
            granted_by=actor_id,
            created_at=datetime.now(UTC),
            revoked_at=None,
            revoked_by=None,
        )
        self.records.setdefault(principal_id, []).append(record)
        self.audit_events.append(("permission.granted", actor_id, principal_id))
        return record, True

    async def list_grants(self, principal_id: str) -> tuple[PermissionGrantRecord, ...]:
        return tuple(self.records.get(principal_id, ()))

    async def revoke(self, grant_id, *, actor_id: str) -> PermissionGrantRecord | None:
        for principal_id, records in self.records.items():
            for index, record in enumerate(records):
                if record.id == grant_id and record.revoked_at is None:
                    revoked = PermissionGrantRecord(
                        id=record.id,
                        principal_id=record.principal_id,
                        tool_name=record.tool_name,
                        scope=record.scope,
                        allowed_targets=record.allowed_targets,
                        granted_by=record.granted_by,
                        created_at=record.created_at,
                        revoked_at=datetime.now(UTC),
                        revoked_by=actor_id,
                    )
                    records[index] = revoked
                    self.audit_events.append(("permission.revoked", actor_id, principal_id))
                    return revoked
        return None

    async def revoke_principal(self, principal_id: str, *, actor_id: str) -> int:
        records = self.records.get(principal_id, [])
        revoked_count = 0
        for index, record in enumerate(records):
            if record.revoked_at is None:
                records[index] = PermissionGrantRecord(
                    id=record.id,
                    principal_id=record.principal_id,
                    tool_name=record.tool_name,
                    scope=record.scope,
                    allowed_targets=record.allowed_targets,
                    granted_by=record.granted_by,
                    created_at=record.created_at,
                    revoked_at=datetime.now(UTC),
                    revoked_by=actor_id,
                )
                self.audit_events.append(("permission.revoked", actor_id, principal_id))
                revoked_count += 1
        return revoked_count


def send(application, method: str, path: str, payload: dict | None = None):
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, json=payload)

    return asyncio.run(request())


def make_app(*, subject: str = "permission-admin"):
    application = create_app(
        Settings(
            notes_search_allowed_targets=("notes/personal", "notes/team"),
            permission_admin_subjects=("permission-admin",),
        )
    )
    service = InMemoryPermissionService()
    application.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        subject=subject,
        display_name=subject,
    )
    application.dependency_overrides[get_permission_service] = lambda: service
    return application, service


def test_admin_can_grant_list_and_revoke_permissions():
    application, service = make_app()
    created = send(
        application,
        "POST",
        "/api/v1/admin/permissions",
        {
            "principal_id": "member-1",
            "tool_name": "notes.search",
            "scope": "read",
            "allowed_targets": ["notes/personal"],
        },
    )

    assert created.status_code == 201
    grant_id = created.json()["id"]
    assert service.audit_events == [("permission.granted", "permission-admin", "member-1")]

    duplicate = send(
        application,
        "POST",
        "/api/v1/admin/permissions",
        {
            "principal_id": "member-1",
            "tool_name": "notes.search",
            "scope": "read",
            "allowed_targets": ["notes/personal"],
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == grant_id
    assert len(service.audit_events) == 1

    listed = send(application, "GET", "/api/v1/admin/permissions/member-1")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["revoked_at"] is None

    revoked = send(application, "DELETE", f"/api/v1/admin/permissions/grants/{grant_id}")
    assert revoked.status_code == 204
    assert service.audit_events[-1] == ("permission.revoked", "permission-admin", "member-1")


def test_admin_can_revoke_all_principal_permissions():
    application, _ = make_app()
    for target in ("notes/personal", "notes/team"):
        assert (
            send(
                application,
                "POST",
                "/api/v1/admin/permissions",
                {
                    "principal_id": "departing-member",
                    "tool_name": "notes.search",
                    "scope": "read",
                    "allowed_targets": [target],
                },
            ).status_code
            == 201
        )

    response = send(
        application,
        "DELETE",
        "/api/v1/admin/permissions/principals/departing-member",
    )

    assert response.status_code == 200
    assert response.json() == {"principal_id": "departing-member", "revoked_count": 2}


def test_non_admin_cannot_manage_permissions():
    application, _ = make_app(subject="ordinary-member")

    response = send(
        application,
        "POST",
        "/api/v1/admin/permissions",
        {
            "principal_id": "member-1",
            "tool_name": "notes.search",
            "scope": "read",
            "allowed_targets": ["notes/personal"],
        },
    )

    assert response.status_code == 403


def test_admin_cannot_grant_unknown_tool_or_unconfigured_target():
    application, service = make_app()
    unknown_tool = send(
        application,
        "POST",
        "/api/v1/admin/permissions",
        {
            "principal_id": "member-1",
            "tool_name": "shell.execute",
            "scope": "write",
            "allowed_targets": ["*"],
        },
    )
    unknown_target = send(
        application,
        "POST",
        "/api/v1/admin/permissions",
        {
            "principal_id": "member-1",
            "tool_name": "notes.search",
            "scope": "read",
            "allowed_targets": ["notes/private"],
        },
    )

    assert unknown_tool.status_code == 422
    assert unknown_target.status_code == 422
    assert service.audit_events == []


def test_permission_admin_subjects_load_from_environment(monkeypatch):
    monkeypatch.setenv(
        "CORTEXSTONE_PERMISSION_ADMIN_SUBJECTS",
        "oidc|admin-one, oidc|admin-two",
    )

    settings = Settings.from_environment()

    assert settings.permission_admin_subjects == ("oidc|admin-one", "oidc|admin-two")
