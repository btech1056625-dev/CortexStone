"""Authenticated, read-only GitHub issue endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.dependencies import (
    get_authenticated_user,
    get_github_tool_runner,
    get_policy_principal,
)
from cortexstone.security.policy import PolicyPrincipal
from cortexstone.tools.connectors.github import (
    GITHUB_ISSUE_READ_TOOL,
    GitHubIssue,
    GitHubIssueNotFoundError,
    GitHubProviderError,
)
from cortexstone.tools.runner import ToolExecutionDenied, ToolNotRegisteredError, ToolRunner

router = APIRouter(prefix="/github", tags=["github"])


@router.get(
    "/{owner}/{repo}/issues/{issue_number}",
    response_model=GitHubIssue,
)
async def read_issue(
    owner: str,
    repo: str,
    issue_number: Annotated[int, Path(ge=1)],
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    principal: Annotated[PolicyPrincipal, Depends(get_policy_principal)],
    tool_runner: Annotated[ToolRunner, Depends(get_github_tool_runner)],
) -> GitHubIssue:
    """Read one issue only through current server policy and registered executor."""
    if principal.principal_id != user.subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The authenticated principal could not be resolved.",
        )

    action = ProposedAction(
        tool_name=GITHUB_ISSUE_READ_TOOL,
        target_ref=f"{owner}/{repo}",
        arguments={"issue_number": issue_number},
        purpose="Read the requested GitHub issue.",
    )
    try:
        result = await tool_runner.execute(principal, action)
    except ToolExecutionDenied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GitHub issue access is not permitted.",
        ) from None
    except ToolNotRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Connect a GitHub account with access to this repository.",
        ) from None
    except GitHubIssueNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub issue not found.",
        ) from None
    except GitHubProviderError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub could not provide the requested issue.",
        ) from None

    if not isinstance(result, GitHubIssue):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub returned an invalid issue result.",
        )
    return result
