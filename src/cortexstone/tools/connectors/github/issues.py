"""Bounded read-only GitHub issue connector."""

import json
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from cortexstone.agent.schemas.actions import ProposedAction

GITHUB_ISSUE_READ_TOOL = "github.issue.read"
GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
MAX_RESPONSE_BYTES = 512 * 1024


class GitHubProviderError(RuntimeError):
    """Raised when GitHub cannot safely provide a valid issue response."""


class GitHubIssueNotFoundError(GitHubProviderError):
    """Raised when the allowlisted issue does not exist or is not visible."""


class GitHubIssue(BaseModel):
    """Minimal validated issue data returned by the read-only connector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str
    number: int = Field(ge=1)
    title: str = Field(max_length=512)
    state: Literal["open", "closed"]
    body: str | None = Field(max_length=100_000)
    html_url: str
    labels: tuple[str, ...] = Field(max_length=100)


class GitHubIssueReader:
    """Read one issue from a fixed GitHub API using an exact repository allowlist."""

    def __init__(
        self,
        token: str,
        allowed_repositories: tuple[str, ...],
        client: httpx.AsyncClient,
    ) -> None:
        if not token.strip() or any(
            ord(character) < 33 or ord(character) > 126 for character in token
        ):
            raise ValueError("GitHub token must not be empty.")
        if not allowed_repositories:
            raise ValueError("At least one GitHub repository must be allowlisted.")
        self._token = token.strip()
        self._allowed_repositories = frozenset(allowed_repositories)
        self._client = client

    async def __call__(self, action: ProposedAction) -> GitHubIssue:
        """Validate an action again before making a bounded provider request."""
        if action.tool_name != GITHUB_ISSUE_READ_TOOL:
            raise GitHubProviderError("The GitHub issue reader received an unsupported action.")
        if action.target_ref not in self._allowed_repositories:
            raise GitHubProviderError("The requested repository is not configured.")
        if set(action.arguments) != {"issue_number"}:
            raise GitHubProviderError("The issue request arguments are invalid.")
        issue_number = action.arguments["issue_number"]
        if type(issue_number) is not int or issue_number < 1:
            raise GitHubProviderError("The issue number is invalid.")

        url = f"{GITHUB_API_BASE_URL}/repos/{action.target_ref}/issues/{issue_number}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": "CortexStone",
        }

        try:
            async with self._client.stream("GET", url, headers=headers) as response:
                if response.status_code == 404:
                    raise GitHubIssueNotFoundError("The requested GitHub issue was not found.")
                if response.status_code in {401, 403}:
                    raise GitHubProviderError(
                        "GitHub rejected the configured credentials or repository access."
                    )
                if response.status_code != 200:
                    raise GitHubProviderError("GitHub could not complete the issue request.")
                raw_body = await self._read_bounded_response(response)
        except httpx.TimeoutException:
            raise GitHubProviderError("The GitHub issue request timed out.") from None
        except httpx.RequestError:
            raise GitHubProviderError("The GitHub issue request failed.") from None

        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise GitHubProviderError("GitHub returned an invalid issue response.") from None

        return self._validate_issue(payload, action.target_ref, issue_number)

    @staticmethod
    async def _read_bounded_response(response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total_bytes = 0
        async for chunk in response.aiter_bytes():
            total_bytes += len(chunk)
            if total_bytes > MAX_RESPONSE_BYTES:
                raise GitHubProviderError("GitHub returned an oversized issue response.")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _validate_issue(
        payload: Any,
        repository: str,
        issue_number: int,
    ) -> GitHubIssue:
        if not isinstance(payload, Mapping):
            raise GitHubProviderError("GitHub returned an invalid issue response.")
        repository_url = payload.get("repository_url")
        html_url = payload.get("html_url")
        returned_number = payload.get("number")
        returned_repository = _repository_from_api_url(repository_url)
        if (
            type(returned_number) is not int
            or returned_number != issue_number
            or returned_repository is None
            or returned_repository.casefold() != repository.casefold()
            or not _is_expected_issue_url(html_url, repository, issue_number)
        ):
            raise GitHubProviderError("GitHub returned a mismatched issue.")

        labels = payload.get("labels")
        if not isinstance(labels, list) or any(
            not isinstance(label, Mapping) or not isinstance(label.get("name"), str)
            for label in labels
        ):
            raise GitHubProviderError("GitHub returned invalid issue labels.")

        try:
            return GitHubIssue(
                repository=repository,
                number=returned_number,
                title=payload.get("title"),
                state=payload.get("state"),
                body=payload.get("body"),
                html_url=html_url,
                labels=tuple(label["name"] for label in labels),
            )
        except (TypeError, ValueError):
            raise GitHubProviderError("GitHub returned an invalid issue response.") from None


def _repository_from_api_url(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.casefold() != "api.github.com":
        return None
    if parsed.query or parsed.fragment:
        return None
    prefix = "/repos/"
    if not parsed.path.startswith(prefix):
        return None
    repository = parsed.path[len(prefix) :].rstrip("/")
    if repository.count("/") != 1:
        return None
    return repository


def _is_expected_issue_url(url: object, repository: str, issue_number: int) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    expected_path = f"/{repository}/issues/{issue_number}"
    return (
        parsed.scheme == "https"
        and parsed.netloc.casefold() == "github.com"
        and parsed.path.casefold() == expected_path.casefold()
        and not parsed.query
        and not parsed.fragment
    )
