# Restricted tool execution boundary

`ToolRunner.execute()` is the only supported path for tool actions. A model can
propose a typed action, but it cannot select or load executable code. The runner
records the attempt, re-evaluates the server-owned tool policy and current
principal grants, resolves trusted approval evidence when configured, and
dispatches only the executor registered for that exact tool after an `ALLOW`
decision. Unknown tools, disallowed targets, missing grants, and invalid or
missing approval evidence fail closed. Action arguments changed after approval
require new approval evidence.

## What this boundary does not provide

This is an in-process policy and dispatch boundary, **not an operating-system
sandbox**. A registered executor runs with the API process's privileges. The
runner does not isolate filesystem, network, CPU, memory, or credentials, and
does not currently impose an executor timeout. Only trusted, reviewed
application-owned executors may be registered.

Never register model-controlled shell/Python execution, dynamic imports,
unrestricted filesystem or network access, or Docker/socket access. Do not call
connectors directly from application code; doing so bypasses policy, approvals,
and action recording. No production executors are currently registered, and
the API's action-validation route does not execute actions.

Before registering a connector, give it a narrowly scoped server-owned
credential, fixed service hosts and operation scopes, bounded timeouts and
responses, and safe error handling. Treat connector results as untrusted data,
not instructions or authorization for follow-up actions. Verify side effects
independently where applicable. A full OS/container sandbox remains future
work if arbitrary or less-trusted executors are ever needed.
