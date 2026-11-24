# GitHub issue reader

The first provider-backed connector is a read-only issue lookup:

```text
GET /api/v1/github/{owner}/{repo}/issues/{issue_number}
```

The route authenticates the caller and sends a server-created `github.issue.read`
action through `ToolRunner`. The server policy requires an exact repository
target, a current `read` grant, and the sole `issue_number` argument. No
model-supplied URL, host, or arbitrary request headers are accepted. The
executor calls only `https://api.github.com`, does not follow redirects, uses a
10-second request timeout (3 seconds to connect), and caps decompressed response
data at 512 KiB. It validates that the returned repository, issue number, and
canonical GitHub URL match the request before returning a minimal response.
Issue bodies remain untrusted content.

## Configuration and credentials

Set `GITHUB_TOKEN` and comma-separated exact repository names in
`CORTEXSTONE_POLICY_GITHUB_ISSUE_READ_TARGETS` (for example
`octocat/hello-world`). Both settings are required to register the policy and
executor; empty or missing configuration leaves the connector disabled. A
permission administrator must grant the caller `github.issue.read` with `read`
scope and an allowed repository target. The request route does not grant access.

Use a GitHub fine-grained personal access token limited to the configured
repositories and the minimum **Issues: read-only** permission. Keep the token
in the service environment or secret manager, never in source, request bodies,
or logs. Rotate it in GitHub and update the service secret; revoke the old token
after the replacement is deployed. The API does not expose a credential
management endpoint.

The HTTP integration tests use `httpx.MockTransport`; no live GitHub token or
repository was exercised as part of local verification. Calendar, Notes, and
GitHub write operations are not registered. This read-only provider call is
idempotent, so no automatic retries are performed.
