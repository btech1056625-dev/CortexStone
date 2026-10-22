import asyncio

import httpx
import pytest
from pydantic import ValidationError

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.api.config import Settings
from cortexstone.api.dependencies import get_policy_principal
from cortexstone.api.main import create_app
from cortexstone.security.policy import (
    ActionScope,
    PermissionGrant,
    PolicyPrincipal,
)


def request(app, payload: dict) -> httpx.Response:
    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/v1/actions/validate", json=payload)

    return asyncio.run(send_request())


def action(
    *,
    tool_name: str,
    target_ref: str,
    arguments: dict,
) -> ProposedAction:
    return ProposedAction(
        tool_name=tool_name,
        target_ref=target_ref,
        arguments=arguments,
        purpose="Validate a test action",
    )


@pytest.fixture
def configured_app():
    return create_app(Settings(notes_search_allowed_targets=("notes/personal",)))


def test_action_validation_injects_configured_policy_and_principal(configured_app):
    configured_app.dependency_overrides[get_policy_principal] = lambda: PolicyPrincipal(
        principal_id="test-user",
        grants=(
            PermissionGrant(
                tool_name="notes.search",
                scope=ActionScope.READ,
                allowed_targets=frozenset({"notes/personal"}),
            ),
        ),
    )

    response = request(
        configured_app,
        {
            "action": {
                "tool_name": "notes.search",
                "target_ref": "notes/personal",
                "arguments": {"query": "project"},
                "purpose": "Find project notes",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "allow"
    assert response.json()["reason"] == "allowed"
    assert response.json()["risk"] == "low"
    assert len(response.json()["action_hash"]) == 64
    assert response.headers["x-request-id"]


def test_action_validation_denies_missing_grant(configured_app):
    configured_app.dependency_overrides[get_policy_principal] = lambda: PolicyPrincipal(
        principal_id="test-user",
        grants=(),
    )

    response = request(
        configured_app,
        {
            "action": {
                "tool_name": "notes.search",
                "target_ref": "notes/personal",
                "arguments": {"query": "project"},
                "purpose": "Find project notes",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "deny"
    assert response.json()["reason"] == "permission_missing"
    assert response.json()["risk"] == "low"
    assert response.json()["action_hash"] is None


def test_action_validation_fails_closed_without_authentication(configured_app):
    response = request(
        configured_app,
        {
            "action": {
                "tool_name": "notes.search",
                "target_ref": "notes/personal",
                "arguments": {"query": "project"},
                "purpose": "Find project notes",
            }
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert response.json()["request_id"] == response.headers["x-request-id"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"action": {"tool_name": "notes.search"}},
        {
            "action": {
                "tool_name": "notes.search",
                "target_ref": "notes/personal",
                "arguments": {"query": "project"},
                "purpose": "Find project notes",
                "approval": {"approved": True},
            }
        },
    ],
)
def test_invalid_action_requests_use_shared_validation_error(configured_app, payload):
    configured_app.dependency_overrides[get_policy_principal] = lambda: PolicyPrincipal(
        principal_id="test-user",
        grants=(),
    )
    response = request(configured_app, payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "detail" not in response.json()


def test_unhandled_dependency_error_uses_generic_error_envelope(configured_app):
    def fail_principal():
        raise RuntimeError("sensitive internal detail")

    configured_app.dependency_overrides[get_policy_principal] = fail_principal

    response = request(
        configured_app,
        {
            "action": {
                "tool_name": "notes.search",
                "target_ref": "notes/personal",
                "arguments": {"query": "project"},
                "purpose": "Find project notes",
            }
        },
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_server_error"
    assert "sensitive internal detail" not in response.text
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_environment_configuration_registers_exact_targets(monkeypatch):
    monkeypatch.setenv(
        "CORTEXSTONE_POLICY_NOTES_SEARCH_TARGETS",
        "notes/personal, notes/work",
    )

    configured = Settings.from_environment()
    application = create_app(configured)

    assert configured.notes_search_allowed_targets == ("notes/personal", "notes/work")
    principal = PolicyPrincipal(
        principal_id="test-user",
        grants=(
            PermissionGrant(
                tool_name="notes.search",
                scope=ActionScope.READ,
                allowed_targets=frozenset({"notes/work"}),
            ),
        ),
    )
    allowed_target = application.state.policy_engine.evaluate(
        principal,
        action(
            tool_name="notes.search",
            target_ref="notes/work",
            arguments={"query": "test"},
        ),
    )
    blocked_target = application.state.policy_engine.evaluate(
        principal,
        action(
            tool_name="notes.search",
            target_ref="notes/private",
            arguments={"query": "test"},
        ),
    )

    assert allowed_target.status.value == "allow"
    assert blocked_target.reason.value == "target_not_allowlisted"


def test_policy_target_configuration_defaults_to_no_registered_tools(monkeypatch):
    monkeypatch.delenv("CORTEXSTONE_POLICY_NOTES_SEARCH_TARGETS", raising=False)

    application = create_app(Settings.from_environment())

    principal = PolicyPrincipal(principal_id="test-user", grants=())
    decision = application.state.policy_engine.evaluate(
        principal,
        action(
            tool_name="notes.search",
            target_ref="notes/personal",
            arguments={"query": "test"},
        ),
    )

    assert decision.reason.value == "unknown_tool"


def test_settings_reject_duplicate_policy_targets():
    with pytest.raises(ValidationError):
        Settings(notes_search_allowed_targets=("notes/personal", "notes/personal"))
