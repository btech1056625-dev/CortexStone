from datetime import UTC, datetime, timedelta

import pytest

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.security.policy import (
    ActionScope,
    ApprovalEvidence,
    PermissionGrant,
    PolicyEngine,
    PolicyPrincipal,
    PolicyReason,
    PolicyStatus,
    RiskLevel,
    ToolPolicy,
)

READ_TOOL = ToolPolicy(
    tool_name="notes.search",
    scope=ActionScope.READ,
    risk=RiskLevel.LOW,
    allowed_targets=frozenset({"notes/personal"}),
    required_arguments=frozenset({"query"}),
    optional_arguments=frozenset({"limit"}),
)
WRITE_TOOL = ToolPolicy(
    tool_name="notes.create",
    scope=ActionScope.WRITE,
    risk=RiskLevel.LOW,
    allowed_targets=frozenset({"notes/personal"}),
    required_arguments=frozenset({"title", "content"}),
)
PRINCIPAL = PolicyPrincipal(
    principal_id="user-1",
    grants=(
        PermissionGrant(
            tool_name="notes.search",
            scope=ActionScope.READ,
            allowed_targets=frozenset({"notes/personal"}),
        ),
        PermissionGrant(
            tool_name="notes.create",
            scope=ActionScope.WRITE,
            allowed_targets=frozenset({"notes/personal"}),
        ),
    ),
)


def action(
    tool_name: str = "notes.search",
    target_ref: str = "notes/personal",
    arguments: dict | None = None,
) -> ProposedAction:
    return ProposedAction(
        tool_name=tool_name,
        target_ref=target_ref,
        arguments={"query": "project notes"} if arguments is None else arguments,
        purpose="Find relevant project notes",
    )


def engine() -> PolicyEngine:
    return PolicyEngine([READ_TOOL, WRITE_TOOL])


def test_allows_permitted_low_risk_read():
    decision = engine().evaluate(PRINCIPAL, action())

    assert decision.status == PolicyStatus.ALLOW
    assert decision.reason == PolicyReason.ALLOWED
    assert decision.risk == RiskLevel.LOW
    assert decision.action_hash


@pytest.mark.parametrize(
    ("proposed_action", "reason"),
    [
        (action(tool_name="notes.delete"), PolicyReason.UNKNOWN_TOOL),
        (
            action(target_ref="notes/private"),
            PolicyReason.TARGET_NOT_ALLOWLISTED,
        ),
    ],
)
def test_denies_unregistered_tool_or_disallowed_target(proposed_action, reason):
    decision = engine().evaluate(PRINCIPAL, proposed_action)

    assert decision.status == PolicyStatus.DENY
    assert decision.reason == reason


def test_denies_missing_permission():
    decision = engine().evaluate(PolicyPrincipal("user-2", ()), action())

    assert decision.status == PolicyStatus.DENY
    assert decision.reason == PolicyReason.PERMISSION_MISSING


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"query": "notes", "admin": True},
        {"query": object()},
    ],
)
def test_denies_missing_unexpected_or_non_json_arguments(arguments):
    decision = engine().evaluate(PRINCIPAL, action(arguments=arguments))

    assert decision.status == PolicyStatus.DENY
    assert decision.reason == PolicyReason.INVALID_ARGUMENTS


def test_write_requires_approval_bound_to_action_and_target():
    proposed_action = action(
        tool_name="notes.create",
        arguments={"title": "Plan", "content": "Review proposal"},
    )
    policy_engine = engine()
    pending = policy_engine.evaluate(PRINCIPAL, proposed_action)

    assert pending.status == PolicyStatus.REQUIRE_APPROVAL
    assert pending.reason == PolicyReason.APPROVAL_REQUIRED

    evidence = ApprovalEvidence(
        approved=True,
        action_hash=pending.action_hash,
        target_ref=proposed_action.target_ref,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    approved = policy_engine.evaluate(PRINCIPAL, proposed_action, approval=evidence)

    assert approved.status == PolicyStatus.ALLOW


def test_approval_for_changed_arguments_requires_new_approval():
    proposed_action = action(
        tool_name="notes.create",
        arguments={"title": "Plan", "content": "Review proposal"},
    )
    policy_engine = engine()
    initial = policy_engine.evaluate(PRINCIPAL, proposed_action)
    evidence = ApprovalEvidence(
        approved=True,
        action_hash=initial.action_hash,
        target_ref=proposed_action.target_ref,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    changed = action(
        tool_name="notes.create",
        arguments={"title": "Plan", "content": "Changed content"},
    )
    decision = policy_engine.evaluate(PRINCIPAL, changed, approval=evidence)

    assert decision.status == PolicyStatus.REQUIRE_APPROVAL
    assert decision.reason == PolicyReason.APPROVAL_MISMATCH


@pytest.mark.parametrize(
    ("approval", "reason", "status"),
    [
        (
            ApprovalEvidence(False, "hash", "notes/personal", datetime.now(UTC) + timedelta(1)),
            PolicyReason.APPROVAL_REJECTED,
            PolicyStatus.DENY,
        ),
        (
            ApprovalEvidence(
                True, "wrong-hash", "notes/personal", datetime.now(UTC) + timedelta(1)
            ),
            PolicyReason.APPROVAL_MISMATCH,
            PolicyStatus.REQUIRE_APPROVAL,
        ),
        (
            ApprovalEvidence(True, "hash", "notes/personal", datetime.now(UTC) - timedelta(1)),
            PolicyReason.APPROVAL_EXPIRED,
            PolicyStatus.REQUIRE_APPROVAL,
        ),
    ],
)
def test_invalid_approval_never_allows_write(approval, reason, status):
    proposed_action = action(
        tool_name="notes.create",
        arguments={"title": "Plan", "content": "Review proposal"},
    )
    if reason == PolicyReason.APPROVAL_EXPIRED:
        approval = ApprovalEvidence(
            approved=True,
            action_hash=PolicyEngine.action_hash(proposed_action),
            target_ref=proposed_action.target_ref,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

    decision = engine().evaluate(PRINCIPAL, proposed_action, approval=approval)

    assert decision.status == status
    assert decision.reason == reason


def test_action_hash_is_stable_for_equivalent_json_arguments():
    left = action(arguments={"query": "notes", "limit": 5})
    right = action(arguments={"limit": 5, "query": "notes"})

    assert PolicyEngine.action_hash(left) == PolicyEngine.action_hash(right)


def test_rejects_duplicate_tool_policy():
    with pytest.raises(ValueError, match="Duplicate tool policy"):
        PolicyEngine([READ_TOOL, READ_TOOL])
