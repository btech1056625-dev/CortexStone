"""Deterministic backend authorization for proposed tool actions.

Re-exports core policy definitions and PolicyEngine from engine.py for compatibility.
"""

from __future__ import annotations

from cortexstone.security.policy.engine import (
    ActionScope,
    ApprovalEvidence,
    ApprovalService,
    PermissionGrant,
    PermissionService,
    PolicyDecision,
    PolicyEngine,
    PolicyPrincipal,
    PolicyReason,
    PolicyStatus,
    RiskLevel,
    ToolPolicy,
)

__all__ = [
    "ActionScope",
    "ApprovalEvidence",
    "ApprovalService",
    "PermissionGrant",
    "PermissionService",
    "PolicyDecision",
    "PolicyEngine",
    "PolicyPrincipal",
    "PolicyReason",
    "PolicyStatus",
    "RiskLevel",
    "ToolPolicy",
]
