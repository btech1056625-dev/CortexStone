"""Tests for the permission-controlled GitHub issue-read workflow."""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.config import Settings
from cortexstone.api.dependencies import (
    build_policy_engine,
    get_action_run_service,
    get_authenticated_user,
    get_policy_principal,
)
from cortexstone.api.main import create_app
from cortexstone.security.action_runs import ActionRunStatus
from cortexstone.security.policy import ActionScope, PermissionGrant, PolicyPrincipal
from cortexstone.tools.connectors.github import (
    GITHUB_ISSUE_READ_TOOL,
    GitHubIssueReader,
    GitHubProviderError,
)

TARGET = "octocat/hello-world"
ISSUE_NUMBER = 42


def issue_payload(
    *,
    repository: str = TARGET,
    number: int = ISSUE_NUMBER,
) -> dict:
    return {
        "repository_url": f"https://api.github.com/repos/{repository}",
        "number": number,
        "title": "A test issue",
        "state": "open",
        "body": "Issue description.",
        "html_url": f"https://github.com/{repository}/issues/{number}",
        "labels": [{"name": "bug"}],
    }


class InMemoryActionRunRecorder:
    def __init__(self) -> None:
        self.attempts: list[tuple[str, object]] = []
        self.transitions: list[tuple[UUID, ActionRunStatus]] = []

    async def create_attempt(self, principal_id: str, action) -> UUID:
        self.attempts.append((principal_id, action))
        return uuid4()

    async def transition(
        self,
        run_id: UUID,
        status: ActionRunStatus,
        *,
        policy_reason=None,
        failure_code=None,
        approval_accepted: bool = False,
    ) -> None:
        self.transitions.append((run_id, status))


def make_github_app(handler, *, grants: tuple[PermissionGrant, ...] | None = None):
    settings = Settings(
        github_token="fake-test-token",
        github_issue_read_allowed_targets=(TARGET,),
    )
    application = create_app(settings)
    original_client = application.state.github_http_client
    recorder = InMemoryActionRunRecorder()

    async def replace_client() -> httpx.AsyncClient:
        await original_client.aclose()
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
            timeout=httpx.Timeout(2.0),
        )

    client = asyncio.run(replace_client())
    reader = GitHubIssueReader(
        token=settings.github_token,
        allowed_repositories=settings.github_issue_read_allowed_targets,
        client=client,
    )
    application.state.github_http_client = client
    application.state.github_issue_reader = reader
    application.state.tool_executors = {GITHUB_ISSUE_READ_TOOL: reader}
    application.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        subject="verified-user",
        display_name="Verified User",
    )
    application.dependency_overrides[get_policy_principal] = lambda: PolicyPrincipal(
        principal_id="verified-user",
        grants=(
            grants
            if grants is not None
            else (
                PermissionGrant(
                    tool_name=GITHUB_ISSUE_READ_TOOL,
                    scope=ActionScope.READ,
                    allowed_targets=frozenset({TARGET}),
                ),
            )
        ),
    )
    application.dependency_overrides[get_action_run_service] = lambda: recorder
    return application, client, recorder


def request_issue(application, target: str = TARGET) -> httpx.Response:
    owner, repository = target.split("/", maxsplit=1)

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.get(f"/api/v1/github/{owner}/{repository}/issues/{ISSUE_NUMBER}")

    return asyncio.run(send_request())


def test_github_issue_route_authorizes_and_dispatches_registered_reader():
    provider_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        return httpx.Response(200, json=issue_payload())

    application, client, recorder = make_github_app(handler)
    try:
        response = request_issue(application)
    finally:
        asyncio.run(client.aclose())

    assert response.status_code == 200
    assert response.json()["repository"] == TARGET
    assert response.json()["number"] == ISSUE_NUMBER
    assert response.json()["title"] == "A test issue"
    assert len(provider_requests) == 1
    assert provider_requests[0].method == "GET"
    assert provider_requests[0].url == (
        "https://api.github.com/repos/octocat/hello-world/issues/42"
    )
    assert provider_requests[0].headers["authorization"] == "Bearer fake-test-token"
    assert recorder.attempts[0][0] == "verified-user"
    assert [status for _, status in recorder.transitions] == [
        ActionRunStatus.RUNNING,
        ActionRunStatus.SUCCEEDED,
    ]


def test_github_issue_route_denies_missing_permission_before_provider_request():
    provider_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        return httpx.Response(200, json=issue_payload())

    application, client, recorder = make_github_app(handler, grants=())
    try:
        response = request_issue(application)
    finally:
        asyncio.run(client.aclose())

    assert response.status_code == 403
    assert provider_requests == []
    assert [status for _, status in recorder.transitions] == [ActionRunStatus.DENIED]


def test_github_issue_route_rejects_unallowlisted_repository_before_provider_request():
    provider_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        return httpx.Response(200, json=issue_payload())

    application, client, recorder = make_github_app(handler)
    try:
        response = request_issue(application, "another/private-repo")
    finally:
        asyncio.run(client.aclose())

    assert response.status_code == 403
    assert provider_requests == []
    assert [status for _, status in recorder.transitions] == [ActionRunStatus.DENIED]


def test_github_issue_route_rejects_mismatched_provider_resource():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=issue_payload(repository="another/repo"))

    application, client, recorder = make_github_app(handler)
    try:
        response = request_issue(application)
    finally:
        asyncio.run(client.aclose())

    assert response.status_code == 502
    assert response.json()["error"]["message"] == ("GitHub could not provide the requested issue.")
    assert [status for _, status in recorder.transitions] == [
        ActionRunStatus.RUNNING,
        ActionRunStatus.FAILED,
    ]


def test_github_issue_reader_rejects_oversized_provider_response():
    async def exercise() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, content=b"x" * (512 * 1024 + 1))
            )
        )
        reader = GitHubIssueReader("fake-test-token", (TARGET,), client)
        action = ProposedAction(
            tool_name=GITHUB_ISSUE_READ_TOOL,
            target_ref=TARGET,
            arguments={"issue_number": ISSUE_NUMBER},
            purpose="Test bounded response handling.",
        )
        try:
            with pytest.raises(GitHubProviderError, match="oversized"):
                await reader(action)
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_github_policy_registers_only_when_enabled_with_exact_targets():
    disabled = build_policy_engine(
        (),
        github_issue_read_allowed_targets=(TARGET,),
        github_enabled=False,
    )
    enabled = build_policy_engine(
        (),
        github_issue_read_allowed_targets=(TARGET,),
        github_enabled=True,
    )

    assert disabled.get_tool_policy(GITHUB_ISSUE_READ_TOOL) is None
    policy = enabled.get_tool_policy(GITHUB_ISSUE_READ_TOOL)
    assert policy is not None
    assert policy.scope == ActionScope.READ
    assert policy.allowed_targets == frozenset({TARGET})
    assert policy.required_arguments == frozenset({"issue_number"})


@pytest.mark.parametrize(
    "target",
    ["octocat/*", "octocat/hello-world/private", "https://example.com/repo", "../repo"],
)
def test_settings_reject_non_exact_github_repository_targets(target):
    with pytest.raises(ValueError, match="exact owner/repository"):
        Settings(github_issue_read_allowed_targets=(target,))
