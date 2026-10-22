"""FastAPI dependencies for policy services and trusted identity context."""

from fastapi import HTTPException, Request, status

from cortexstone.security.policy import (
    ActionScope,
    PolicyEngine,
    PolicyPrincipal,
    RiskLevel,
    ToolPolicy,
)


def get_policy_engine(request: Request) -> PolicyEngine:
    """Resolve the application-scoped policy engine."""
    return request.app.state.policy_engine


def get_policy_principal() -> PolicyPrincipal:
    """Fail closed until authentication can provide a trusted principal."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication is not configured.",
    )


def build_policy_engine(allowed_targets: tuple[str, ...]) -> PolicyEngine:
    """Create policies from validated server configuration."""
    policies = []
    if allowed_targets:
        policies.append(
            ToolPolicy(
                tool_name="notes.search",
                scope=ActionScope.READ,
                risk=RiskLevel.LOW,
                allowed_targets=frozenset(allowed_targets),
                required_arguments=frozenset({"query"}),
                optional_arguments=frozenset({"limit"}),
            )
        )
    return PolicyEngine(policies)
