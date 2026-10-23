"""Deterministic server-side policy engine for validating and authorizing proposed actions.

Co-owned by Raghav (Cybersecurity & Security Enforcement).
Core Invariant: The model proposes actions; the backend policy engine authorizes them.
Never trust model-supplied risk tiers, safety claims, or approval flags.
Fail closed on missing, invalid, or ambiguous security context.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from cortexstone.agent.schemas.actions import ProposedAction

logger = logging.getLogger(__name__)


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
    PERMISSION_REVOKED = "permission_revoked"
    UNAUTHENTICATED = "unauthenticated"
    INVALID_ACTION = "invalid_action"
    INVALID_ARGUMENTS = "invalid_arguments"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_REVOKED = "approval_revoked"
    APPROVAL_MISMATCH = "approval_mismatch"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_PRINCIPAL_MISMATCH = "approval_principal_mismatch"
    SERVICE_ERROR = "service_error"


@dataclass(frozen=True)
class ToolPolicy:
    """Server-owned policy for one registered tool."""

    tool_name: str
    scope: ActionScope
    risk: RiskLevel
    allowed_targets: frozenset[str]
    required_arguments: frozenset[str] = field(default_factory=frozenset)
    optional_arguments: frozenset[str] = field(default_factory=frozenset)
    require_approval: bool = False

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
    revoked: bool = False
    granted: bool = True


@dataclass(frozen=True)
class PolicyPrincipal:
    """Trusted authorization context resolved by the backend."""

    principal_id: str
    grants: tuple[PermissionGrant, ...]
    authenticated: bool = True

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
    principal_id: str | None = None
    revoked: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    """Deterministic authorization decision for an action proposal."""

    status: PolicyStatus
    reason: PolicyReason
    action_hash: str | None = None
    risk: RiskLevel | None = None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PolicyStatus):
            return self.status == other
        if isinstance(other, str):
            return self.status == other or self.status.value == other
        if isinstance(other, PolicyDecision):
            return (
                self.status == other.status
                and self.reason == other.reason
                and self.action_hash == other.action_hash
                and self.risk == other.risk
            )
        return False

    def __hash__(self) -> int:
        return hash((self.status, self.reason, self.action_hash, self.risk))


@runtime_checkable
class ApprovalService(Protocol):
    """Protocol for external approval storage and verification."""

    def get_approval(
        self,
        principal_id: str,
        action_hash: str,
        target_ref: str,
    ) -> ApprovalEvidence | None:
        """Retrieve approval record matching principal, action hash, and target."""
        ...


@runtime_checkable
class PermissionService(Protocol):
    """Protocol for external permission lookup and revocation checks."""

    def get_grants(
        self,
        principal_id: str,
    ) -> Sequence[PermissionGrant]:
        """Retrieve current active grants for a principal."""
        ...


class PolicyEngine:
    """Evaluate proposed actions against server policy and trusted grants."""

    def __init__(
        self,
        tool_policies: Iterable[ToolPolicy],
        *,
        approval_service: ApprovalService | None = None,
        permission_service: PermissionService | None = None,
    ) -> None:
        self._tool_policies: dict[str, ToolPolicy] = {}
        for policy in tool_policies:
            if policy.tool_name in self._tool_policies:
                raise ValueError(f"Duplicate tool policy: {policy.tool_name}")
            self._tool_policies[policy.tool_name] = policy
        self._approval_service = approval_service
        self._permission_service = permission_service

    def evaluate(
        self,
        principal: PolicyPrincipal,
        action: ProposedAction,
        *,
        approval: ApprovalEvidence | None = None,
        now: datetime | None = None,
    ) -> PolicyDecision:
        """Return a policy decision; this method never executes the action."""
        # Step 1: Validate action structure and registered tool
        if not isinstance(action, ProposedAction):
            try:
                action = ProposedAction.model_validate(action)
            except Exception:
                logger.warning("Rejected malformed action structure")
                return PolicyDecision(PolicyStatus.DENY, PolicyReason.INVALID_ACTION)

        policy = self._tool_policies.get(action.tool_name)
        if policy is None:
            return PolicyDecision(PolicyStatus.DENY, PolicyReason.UNKNOWN_TOOL)

        # Step 2: Validate target against registered tool's permitted scope
        if action.target_ref not in policy.allowed_targets:
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.TARGET_NOT_ALLOWLISTED,
                risk=policy.risk,
            )

        # Step 3: Check principal and authentication
        if (
            principal is None
            or not isinstance(principal, PolicyPrincipal)
            or not getattr(principal, "authenticated", True)
            or not principal.principal_id
            or not principal.principal_id.strip()
        ):
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.UNAUTHENTICATED,
                risk=policy.risk,
            )

        # Step 4: Validate principal permissions and check revocation
        try:
            if self._permission_service is not None:
                grants = self._permission_service.get_grants(principal.principal_id)
            else:
                grants = principal.grants
        except Exception:
            logger.exception("Permission service failure during grant resolution")
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.SERVICE_ERROR,
                risk=policy.risk,
            )

        matching_tool_grants = [
            g for g in grants if g.tool_name == action.tool_name and g.scope == policy.scope
        ]
        if not matching_tool_grants:
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.PERMISSION_MISSING,
                risk=policy.risk,
            )

        # Check for matching target grant
        matching_target_grants = [
            g for g in matching_tool_grants if action.target_ref in g.allowed_targets
        ]
        if not matching_target_grants:
            # Check if any matching tool grant was revoked
            if any(
                getattr(g, "revoked", False) or not getattr(g, "granted", True)
                for g in matching_tool_grants
            ):
                return PolicyDecision(
                    PolicyStatus.DENY,
                    PolicyReason.PERMISSION_REVOKED,
                    risk=policy.risk,
                )
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.PERMISSION_MISSING,
                risk=policy.risk,
            )

        # Check if grant has been revoked
        if any(
            getattr(g, "revoked", False) or not getattr(g, "granted", True)
            for g in matching_target_grants
        ):
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.PERMISSION_REVOKED,
                risk=policy.risk,
            )

        # Step 5: Validate arguments contract
        if not isinstance(action.arguments, dict) or not self._arguments_are_json(action.arguments):
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.INVALID_ARGUMENTS,
                risk=policy.risk,
            )

        try:
            action_hash = self.action_hash(action)
        except Exception:
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.INVALID_ARGUMENTS,
                risk=policy.risk,
            )

        argument_names = set(action.arguments.keys())
        allowed_arguments = policy.required_arguments | policy.optional_arguments
        if not policy.required_arguments.issubset(argument_names) or not argument_names.issubset(
            allowed_arguments
        ):
            return PolicyDecision(
                PolicyStatus.DENY,
                PolicyReason.INVALID_ARGUMENTS,
                action_hash,
                policy.risk,
            )

        # Step 6: Derive approval requirement strictly from server policy
        approval_required = (
            policy.scope == ActionScope.WRITE
            or policy.risk != RiskLevel.LOW
            or policy.require_approval
        )

        if not approval_required:
            return PolicyDecision(
                PolicyStatus.ALLOW,
                PolicyReason.ALLOWED,
                action_hash,
                policy.risk,
            )

        # Step 7: Apply approval policy
        if approval is None and self._approval_service is not None:
            try:
                approval = self._approval_service.get_approval(
                    principal.principal_id, action_hash, action.target_ref
                )
            except Exception:
                logger.exception("Approval service failure during evaluation")
                return PolicyDecision(
                    PolicyStatus.DENY,
                    PolicyReason.SERVICE_ERROR,
                    action_hash,
                    policy.risk,
                )

        eval_time = now or datetime.now(UTC)
        approval_decision = self._evaluate_approval(
            approval, action_hash, action.target_ref, principal.principal_id, eval_time
        )
        if approval_decision is not None:
            return PolicyDecision(
                approval_decision[0],
                approval_decision[1],
                action_hash,
                policy.risk,
            )

        return PolicyDecision(
            PolicyStatus.ALLOW,
            PolicyReason.ALLOWED,
            action_hash,
            policy.risk,
        )

    @staticmethod
    def canonical_action_representation(action: ProposedAction) -> str:
        """Deterministic JSON representation of tool, target, and arguments."""
        canonical_action = {
            "arguments": action.arguments,
            "target_ref": action.target_ref,
            "tool_name": action.tool_name,
        }
        return json.dumps(
            canonical_action,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def action_hash(cls, action: ProposedAction) -> str:
        """Hash tool, exact target, and canonical arguments for approval binding."""
        encoded = cls.canonical_action_representation(action).encode("utf-8")
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
        principal_id: str,
        now: datetime,
    ) -> tuple[PolicyStatus, PolicyReason] | None:
        if now.tzinfo is None or now.utcoffset() is None:
            return PolicyStatus.REQUIRE_APPROVAL, PolicyReason.APPROVAL_EXPIRED
        if approval is None:
            return PolicyStatus.REQUIRE_APPROVAL, PolicyReason.APPROVAL_REQUIRED
        if not approval.approved:
            return PolicyStatus.DENY, PolicyReason.APPROVAL_REJECTED
        if getattr(approval, "revoked", False):
            return PolicyStatus.DENY, PolicyReason.APPROVAL_REVOKED
        if approval.principal_id is not None and approval.principal_id != principal_id:
            return PolicyStatus.DENY, PolicyReason.APPROVAL_PRINCIPAL_MISMATCH
        if approval.action_hash != action_hash or approval.target_ref != target_ref:
            return PolicyStatus.REQUIRE_APPROVAL, PolicyReason.APPROVAL_MISMATCH

        expires_at = approval.expires_at
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            return PolicyStatus.REQUIRE_APPROVAL, PolicyReason.APPROVAL_EXPIRED
        if expires_at <= now:
            return PolicyStatus.REQUIRE_APPROVAL, PolicyReason.APPROVAL_EXPIRED
        return None
