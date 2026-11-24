# Security tests

Exercise default-deny permissions, approval binding and expiry, revocation, prompt-injection boundaries, cross-owner access, restricted ToolRunner dispatch, and seeded-secret redaction. Assert denied and unregistered operations never reach an executor. ToolRunner is an in-process policy boundary, not an OS sandbox.
