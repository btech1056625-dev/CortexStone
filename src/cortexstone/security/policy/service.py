"""Deterministic backend authorization for proposed tool actions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from cortexstone.agent.schemas.actions import ProposedAction


class ActionScope(StrEnum):
    READ = "read"
    WRITE = "write"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PolicyStatus(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class PolicyReason(StrEnum):
    ALLOWED = "allowed"
    UNKNOWN_TOOL = "unknown_tool"
    TARGET_NOT_ALLOWLISTED = "target_not_allowlisted"
    PERMISSION_MISSING = "permission_missing"
    INVALID_ARGUMENTS = "invalid_arguments"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_MISMATCH = "approval_mismatch"
    APPROVAL_EXPIRED = "approval_expired"


@dataclass(frozen=True)
class ToolPolicy:
    """Server-owned policy for one registered tool."""

    tool_name: str
    scope: ActionScope
    risk: RiskLevel
    allowed_targets: frozenset[str]
    required_arguments: frozenset[str] = field(default_factory=frozenset)
    optional_arguments: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.tool_name.strip():
            raise ValueError("Tool policy name must not be empty")
        if not self.allowed_targets or any(not target.strip() for target in self.allowed_targets):
            raise ValueError("Tool policy must define non-empty exact target allowlists")
        if self.required_arguments & self.optional_arguments:
            raise ValueError("Required and optional arguments must be disjoint")


@dataclass(frozen=True)
class PermissionGrant:
    """A principal's exact tool, scope, and target grant."""

    tool_name: str
    scope: ActionScope
    allowed_targets: frozenset[str]


@dataclass(frozen=True)
class PolicyPrincipal:
    """Trusted authorization context resolved by the backend."""

    principal_id: str
    grants: tuple[PermissionGrant, ...]

    def __post_init__(self) -> None:
        if not self.principal_id.strip():
            raise ValueError("Principal ID must not be empty")


@dataclass(frozen=True)
class ApprovalEvidence:
    """Trusted persisted approval evidence, never populated from model output."""

    approved: bool
    action_hash: str
    target_ref: str
    expires_at: datetime


@dataclass(frozen=True)
class PolicyDecision:
    status: PolicyStatus
    reason: PolicyReason
    action_hash: str | None = None
    risk: RiskLevel | None = None


class PolicyEngine:
    """Evaluate proposed actions against server policy and trusted grants."""

    def __init__(self, tool_policies: Iterable[ToolPolicy]) -> None:
        self._tool_policies: dict[str, ToolPolicy] = {}
        for policy in tool_policies:
            if policy.tool_name in self._tool_policies:
                raise ValueError(f"Duplicate tool policy: {policy.tool_name}")
            self._tool_policies[policy.tool_name] = policy

    def evaluate(
        self,
        principal: PolicyPrincipal,
        action: ProposedAction,
        *,
        approval: ApprovalEvidence | None = None,
        now: datetime | None = None,
    ) -> PolicyDecision:
        """Return a policy decision; this method never executes the action."""
        policy = self._tool_policies.get(action.tool_name)
        if policy is None:
            return PolicyDecision(PolicyStatus.DENY, PolicyReason.UNKNOWN_TOOL)

        if action.target_ref not in policy.allowed_targets:
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.TARGET_NOT_ALLOWLISTED,
                risk=policy.risk,
            )

        grant = next(
            (
                grant
                for grant in principal.grants
                if grant.tool_name == action.tool_name
                and grant.scope == policy.scope
                and action.target_ref in grant.allowed_targets
            ),
            None,
        )
        if grant is None:
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.PERMISSION_MISSING,
                risk=policy.risk,
            )

        argument_names = set(action.arguments)
        allowed_arguments = policy.required_arguments | policy.optional_arguments
        if not self._arguments_are_json(action.arguments):
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.INVALID_ARGUMENTS,
                risk=policy.risk,
            )
        action_hash = self.action_hash(action)
        if not policy.required_arguments.issubset(argument_names) or not argument_names.issubset(
            allowed_arguments
        ):
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.INVALID_ARGUMENTS,
                action_hash,
                policy.risk,
            )

        approval_required = policy.scope == ActionScope.WRITE or policy.risk != RiskLevel.LOW
        if not approval_required:
            return PolicyDecision(
                PolicyStatus.ALLOW, PolicyReason.ALLOWED, action_hash, policy.risk
            )

        approval_decision = self._evaluate_approval(
            approval, action_hash, action.target_ref, now or datetime.now(UTC)
        )
        if approval_decision is not None:
            return PolicyDecision(
                approval_decision[0],
                approval_decision[1],
                action_hash,
                policy.risk,
            )

        return PolicyDecision(PolicyStatus.ALLOW, PolicyReason.ALLOWED, action_hash, policy.risk)

    @staticmethod
    def action_hash(action: ProposedAction) -> str:
        """Hash tool, exact target, and canonical arguments for approval binding."""
        canonical_action = {
            "tool_name": action.tool_name,
            "target_ref": action.target_ref,
            "arguments": action.arguments,
        }
        encoded = json.dumps(
            canonical_action,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _arguments_are_json(arguments: dict[str, Any]) -> bool:
        try:
            json.dumps(arguments, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            return False
        return True

    @staticmethod
    def _evaluate_approval(
        approval: ApprovalEvidence | None,
        action_hash: str,
        target_ref: str,
        now: datetime,
    ) -> tuple[PolicyStatus, PolicyReason] | None:
        if now.tzinfo is None or now.utcoffset() is None:
            return PolicyStatus.REQUIRE_APPROVAL, PolicyReason.APPROVAL_EXPIRED
        if approval is None:
            return PolicyStatus.REQUIRE_APPROVAL, PolicyReason.APPROVAL_REQUIRED
        if not approval.approved:
            return PolicyStatus.DENY, PolicyReason.APPROVAL_REJECTED
        if approval.action_hash != action_hash or approval.target_ref != target_ref:
            return PolicyStatus.REQUIRE_APPROVAL, PolicyReason.APPROVAL_MISMATCH

        expires_at = approval.expires_at
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            return PolicyStatus.REQUIRE_APPROVAL, PolicyReason.APPROVAL_EXPIRED
        if expires_at <= now:
            return PolicyStatus.REQUIRE_APPROVAL, PolicyReason.APPROVAL_EXPIRED
        return None
