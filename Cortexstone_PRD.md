# Cortexstone — Product Requirements Document (PRD) v2.0

**Version:** 2.0  
**Updated:** 15 October 2026  
**Program:** NVIDIA × Nebius Global AI Hackathon — Personal AI track  
**Team:** 8 members  
**Product promise:** **Remember. Act. Protect.**

## 1. Product overview

Cortexstone is a private, always-on AI assistant for developers and, over time, everyday users. It remembers useful context across sessions, proactively coordinates recurring work across connected tools, and protects users through permission-controlled execution and verifiable action history.

**One-line positioning:** An AI assistant that remembers your context, follows through on tasks, and earns trust before it acts.

Cortexstone is not intended to be just another conversational chatbot. Its product value is the combination of:
- **Remember:** persistent, source-aware, editable memory.
- **Act:** scheduled jobs, reusable workflows, and resilient task execution.
- **Protect:** least-privilege tool access, approval gates, sandboxing, secret redaction, and traceable outcomes.

**Product principle:** Models may propose plans and tool calls; Cortexstone's backend policy layer decides whether an action is permitted. Every consequential tool action must pass through that policy layer.

## 2. Problem statement

People use AI that can answer questions, but still have to repeatedly supply context, coordinate tools manually, verify what an agent did, and recover when automation fails. Unrestricted agents introduce additional risks when they can access repositories, calendars, credentials, or external write operations.

### Core pain points and product responses

| User pain point | Cortexstone response | How it will be measured |
|---|---|---|
| Repeatedly explaining context | Persistent, editable memory across sessions | Relevant facts recalled correctly on a fixed test set |
| Losing previous decisions and information | Semantic and temporal retrieval with source/time references | Retrieval accuracy and source correctness |
| Repeating routine tasks | Reusable, user-approved skills and scheduled workflows | End-to-end task completion rate |
| Fear of unrestricted AI access | Per-tool permissions, least privilege, sandboxing, and approval gates | Zero unauthorized actions executed in adversarial tests |
| Not knowing what the AI has done | Execution history, explicit statuses, and outcome verification | Every tool action is traceable; reported completion matches actual result |
| AI forgetting or failing halfway through a task | Durable workflow state, bounded retries, and recovery | Recovery from simulated failures without duplicate side effects |

### Goals
1. Recall useful information across sessions and provide provenance where available.
2. Proactively deliver a daily brief and run scheduled jobs without the user's laptop online.
3. Propose reusable skills after repeated tasks, with user approval before activation.
4. Make actions understandable, permission-bound, auditable, and verifiably completed.
5. Detect exposed secrets in connected repositories and prevent raw detected secrets from being sent to the model or logs.
6. Deploy an always-on version on Nebius using at least one eligible NVIDIA open model through Token Factory.

### Non-goals for this hackathon MVP
- Multi-user/team accounts, mobile app, voice interface, model training or fine-tuning.
- More than three initial connectors: GitHub, Google Calendar, and Notes.
- Arbitrary shell execution or unrestricted autonomous writes.
- A general-purpose consumer assistant with broad integrations before the developer-focused workflow is proven.

## 3. Users and key scenarios

**Primary MVP persona:** a student or early-career developer managing repositories, CI status, deadlines, notes, and learning goals across multiple tools. The team is the first test group.

**Longer-term audience:** everyday users who need reliable memory, reminders, and safe task follow-through. This broadens the product direction, but does not expand the hackathon connector scope.

| Scenario | Trigger | Expected behavior |
|---|---|---|
| Morning brief | Scheduled daily run (target: 08:00 user-configured time) | Gather authorized GitHub activity, CI status, calendar events, and deadlines; send a prioritized Telegram brief with links and clear source context |
| Recall | User asks what happened on a project last week | Retrieve dated memories and answer with source references; say when evidence is missing or uncertain |
| Repeated task | A workflow is performed repeatedly | Draft a reusable skill; explain what it will do and request approval before enabling it |
| Secret finding | Guardian detects a seeded test secret in a repository | Store a redacted finding, notify the user, and optionally propose a draft remediation PR; never merge automatically |
| Risky action | Agent proposes a merge, send, delete, or other external write | Show action, target, and effects; require explicit approval tied to that action before execution |
| Forget | User asks to forget a memory | Delete the relevant memory and its embedding from retrieval; show a deletion result without retaining the forgotten content in the audit record |
| Failed workflow | Connector or worker fails during a job | Persist status and checkpoint, retry only within policy, avoid duplicate side effects, and report the final state honestly |
| Inspect an action | User opens execution history | Show requested action, tool, target, status, approval state, timestamps, and verified outcome/error |

## 4. Product requirements and priorities

Priority definitions: **P0 = required for MVP; P1 = should ship if P0 is stable; P2 = stretch.**

### 4.1 Living Memory — Remember

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---|---|
| M1 | Three memory types: profile facts, episodic timeline, and approved skills | P0 | A fact saved in one session can be retrieved in a separate session |
| M2 | Semantic and temporal recall | P0 | A query about a past week returns relevant dated items and source references |
| M3 | Provenance and uncertainty | P0 | Answers distinguish stored facts from inference and do not fabricate sources |
| M4 | Verifiable forget | P0 | Deleted items and embeddings are no longer retrievable; audit record confirms deletion without reproducing forgotten content |
| M5 | Memory inspector for viewing and editing entries | P1 | User can edit an entry and a subsequent retrieval reflects the change |
| M6 | User-controlled memory export | P1 | User can export stored memory in a documented, usable format |

### 4.2 Proactive Autopilot — Act

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---|---|
| A1 | Scheduled Telegram morning brief | P0 | Brief arrives on schedule with prioritized authorized data and source links |
| A2 | Always-on scheduled jobs | P0 | Job runs while the user's laptop is offline |
| A3 | Reusable skills proposed after repeated tasks | P1 | Agent drafts a skill and requires approval before it becomes runnable |
| A4 | Approval for sensitive or external writes | P0 | Merge, send, delete, and other configured risky writes do not run before explicit approval |
| A5 | Durable job state and bounded retries | P0 | Job status/checkpoint survives worker restart; retries are bounded and visible |
| A6 | Idempotency for retried side effects | P0 | A simulated retry does not create duplicate external side effects where the connector supports idempotency or deduplication |
| A7 | Honest task status | P0 | UI/messages distinguish queued, running, awaiting approval, succeeded, failed, and cancelled; success requires a tool result or verification |

### 4.3 Guardian Mode — Protect

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---|---|
| G1 | Secret scan of connected repositories | P0 | All five seeded test secrets are detected; raw values are redacted before model/log ingestion |
| G2 | Dependency vulnerability check | P1 | A known vulnerable test dependency is reported with severity and package/version |
| G3 | Risky GitHub Actions workflow check | P1 | Test workflows with unpinned actions or excessive permissions are flagged |
| G4 | Draft remediation PR | P1 | Proposed PR remains draft and cannot merge without explicit approval |
| G5 | Periodic security posture summary | P2 | Summary lists findings, severity, status, and stale credentials where safely available |

### 4.4 Trust and execution layer

| ID | Requirement | Priority | Acceptance criteria |
|---|---|---|---|
| T1 | Central policy enforcement for every tool call | P0 | No connector/tool path bypasses permission checks |
| T2 | Least-privilege connector scopes | P0 | Read-only by default; each write capability is a separate grant |
| T3 | Sandbox and explicit filesystem/network allowlists | P0 | Tool execution cannot access resources outside the configured allowlist in the test environment |
| T4 | Action-bound approvals | P0 | Approval is tied to a specific action and target; material changes invalidate the approval |
| T5 | Append-only execution audit | P0 | Every tool attempt records timestamp, tool, target/input summary, reason, approval state, status, and output/error summary without secrets |
| T6 | Permission revocation | P0 | Revoking a grant blocks subsequent calls immediately |
| T7 | Prompt-injection resistance | P0 | Instructions found in repositories, notes, or retrieved content are treated as untrusted data and cannot bypass policy |
| T8 | Verified completion | P0 | Agent cannot label an action complete solely because the model said it was completed; a tool response or independent check is required |

## 5. MVP scope and release gates

### P0 — MVP
- Cross-session memory with profile facts and episodic timeline, source-aware recall, and verifiable forget.
- Telegram morning brief and durable scheduled jobs.
- Central policy checks, per-tool permissions, approval gates, audit history, and sandboxed tool execution.
- Guardian secret scanning with redaction.
- Explicit execution statuses, failure reporting, bounded retries, and basic recovery.
- FastAPI service deployed on Nebius with an eligible NVIDIA open model through Token Factory.
- Three connectors maximum: GitHub, Google Calendar, Notes. A connector may be staged or simulated for the demo if access is unavailable, but this must be disclosed clearly.

### P1 — Should have
- Memory inspector/edit UI, reusable skill generation, dependency and workflow checks, draft remediation PR, memory export.

### P2 — Stretch
- Weekly security posture report and additional integrations. Voice is out of the MVP scope even if reconsidered later.

**Scope rule:** If a P0 is at risk, defer P1/P2 rather than weakening safety or reliability. Freeze feature work before final demo preparation.

## 6. Architecture and technology direction

### Logical components
1. Telegram bot and lightweight web dashboard.
2. FastAPI application/API layer.
3. Agent orchestration and model-routing layer.
4. NVIDIA model inference through Nebius Token Factory.
5. Memory service backed by PostgreSQL and pgvector.
6. Durable scheduler/job queue and background workers.
7. Connector adapters for GitHub, Calendar, and Notes.
8. Guardian scanning and findings service.
9. Central policy/approval/audit service.
10. Sandbox adapter for controlled tool execution.

**Core request flow:** Interface or scheduler → API → agent/orchestrator → memory/model as needed → proposed tool action → policy/permission check → approval when required → sandboxed connector execution → verified result → audit record and user-facing status.

### Stack (planned; compatibility must be tested)
| Layer | Planned choice | Status/guardrail |
|---|---|---|
| Reasoning model | NVIDIA open Nemotron-family model via Nebius Token Factory | Verify exact model ID, availability, quota, latency, and tool-call behavior |
| Routing/summarization | Smaller model available on Token Factory | Verify exact ID; keep policy decisions in deterministic backend code |
| Agent runtime | Hermes Agent as current preferred candidate | Confirm tool integration in a short spike; keep adapter replaceable |
| Sandbox | OpenShell candidate | Do not claim production isolation until compatibility and escape-boundary tests pass; maintain a restricted fallback |
| Hosting | Nebius deployment/serverless where suitable | Verify scheduler/worker behavior and service limits |
| Backend | Python + FastAPI | Planned |
| Memory | PostgreSQL + pgvector | Planned |
| Interface | Telegram + lightweight dashboard | Planned |
| Delivery | Docker + GitHub Actions | Planned |

**Architecture invariant:** model output is untrusted input. Routing, permissions, approval state, job state, and execution results remain controlled by Cortexstone's backend.

## 7. Data model and operational semantics

| Entity | Purpose | Important fields |
|---|---|---|
| facts | Stable user/project facts | id, key, value, source, confidence, created_at, updated_at |
| episodes | Dated events and conversation memories | id, text, embedding, source, occurred_at, created_at |
| skills | Reusable workflows | id, name, definition/version, approved, permissions_required |
| jobs | Durable scheduled or user-requested work | id, type, status, schedule, checkpoint, attempts, idempotency_key, last_error, timestamps |
| action_runs | Individual tool executions | id, job_id, tool, target, status, approval_id, result_summary, error_summary, timestamps |
| permissions | Per-tool grants | tool, scope, granted, updated_at |
| approvals | Explicit approval decisions | id, action_hash, target, requester, decision, expires_at, decided_at |
| audit_log | Append-only security/action record | id, action_run_id, event_type, redacted_summary, approval_state, at |
| findings | Guardian results | id, repo, type, severity, redacted_evidence, status, remediation_url |

Operational rules:
- Jobs have explicit lifecycle states and bounded retry policy.
- Use idempotency keys or connector-specific deduplication for retried writes.
- Never log raw secrets, access tokens, or full sensitive payloads.
- Forget removes the content and embedding from retrieval and any managed copies under Cortexstone's control. The audit log records that deletion occurred, not the deleted content.
- Keep source, timestamp, and confidence/provenance metadata with memory entries.

## 8. Security, privacy, and trust

- **Least privilege:** connectors begin read-only; write scopes are separately granted.
- **Action-bound approval:** show the proposed action, target, and expected effect. Approval must not silently apply to a changed action.
- **Sandbox:** restrict filesystem and network access to explicit allowlists. Sandbox compatibility is a release gate, not an assumption.
- **Secret handling:** credentials belong in a secrets manager or encrypted environment; never store them in memory or prompts. Redact scanner evidence before it reaches model context or logs.
- **Prompt injection:** repository content, notes, and retrieved text are data, not instructions with authority. Every tool action independently passes backend policy.
- **Auditability:** record attempts, approvals, denials, outcomes, and failures with redacted summaries.
- **Data control:** provide inspect/edit/delete for memory; communicate clearly what data each connector can read.
- **Honest claims:** do not describe the product as perfectly secure or fully autonomous. Demonstrate the exact controls and limits in the demo.

## 9. Success metrics and test plan

| Metric | Target | Test method |
|---|---|---|
| Cross-session memory recall | ≥85% on a fixed 20-question set | Score factual correctness and source correctness separately |
| Morning brief delivery | 5/5 scheduled deliveries over five consecutive days | Check scheduler records and Telegram delivery |
| Secret detection | 5/5 seeded test secrets detected | Verify raw values never appear in model inputs or logs |
| Unauthorized risky actions | 0 executed | Attempt denied, revoked, and unapproved actions |
| Forget correctness | 100% of test deletions become unretrievable | Query before/after deletion and inspect redacted audit event |
| Action traceability | 100% of tool attempts have an execution record | Compare connector calls with action history |
| Outcome honesty | 100% of tested failures are not reported as success | Inject connector errors and inspect user-facing status |
| Recovery safety | All defined crash/retry tests recover or fail clearly; no duplicate side effects in supported test cases | Restart worker during a test job and replay retry |
| Deployment availability | ≥95% during final five-day test window | Health checks and uptime records |
| Permission revocation | 100% of subsequent test calls blocked | Revoke grant and immediately retry |

## 10. Team ownership and working agreements

| Workstream | Members | Responsibilities |
|---|---:|---|
| Agent core and routing | 2 | Orchestration, model adapters, tool contracts, prompts, skill generation |
| Memory | 1 | Schema, retrieval, provenance, edit/forget, inspector |
| Guardian | 1 | Secret scan, redaction, findings, remediation proposal |
| Infrastructure | 2 | Nebius deployment, CI/CD, scheduler/workers, monitoring, reliability tests |
| Security and sandbox | 1 | Policy enforcement, permission scopes, approvals, audit, sandbox tests |
| Interface and demo | 1 | Telegram, dashboard, execution history, approval UX, demo/pitch |

Working agreements: daily 15-minute stand-up; one shared task board; reviewed pull requests; deployable main branch early; test every P0 against its acceptance criteria. Keep a seeded demo dataset and recorded fallback.

## 11. Delivery plan and demo

Keep the original 18-day hackathon window, but treat dates as planning targets and re-confirm the official submission deadline. The earlier plan targets a working core loop by Day 6, deployed MVP by Day 13, feature freeze by Day 16, and final demo/submission preparation on Days 17–18.

### Three-minute demo sequence
1. **0:00 — Proactive:** morning brief arrives on Telegram without a fresh prompt.
2. **0:35 — Remember:** ask what happened on a project last week; show dated source references.
3. **1:10 — Act safely:** run a workflow that pauses for approval before an external write.
4. **1:45 — Protect:** Guardian detects a seeded secret, redacts it, and proposes a draft fix.
5. **2:15 — Recover and verify:** show a simulated failure, durable status/retry, and the verified final result.
6. **2:40 — Trust and control:** show audit history and execute “forget this,” confirming the memory is no longer retrievable.
7. **2:55 — Close:** “Remember. Act. Protect.” Explain deployed model and trust boundaries accurately.

### Submission checklist
- Public repository with README, architecture diagram, setup instructions, and threat-model summary.
- Deployed Nebius instance or clear explanation of any infrastructure limitation.
- Three-minute demo and backup recording.
- Exact model names/IDs and Token Factory details verified against actual deployment.
- Seeded test data, test results, and a rehearsed run-through.

## 12. Risks, open questions, and decision log

| Risk/question | Mitigation or decision gate |
|---|---|
| Model IDs, quota, or tool-call support unavailable | Verify immediately; keep model adapter replaceable and use a tested eligible fallback |
| Agent runtime or sandbox integration is difficult | Run a short compatibility spike; keep policy enforcement outside the runtime; use a restricted fallback if needed |
| Scheduled jobs are not supported by the chosen hosting mode | Deploy a separate durable scheduler/worker rather than assuming serverless functions remain alive |
| Connector rate limits or failures | Bounded retries, backoff, visible failures, caching where safe, and idempotency |
| Prompt injection in repository/notes content | Treat retrieved content as untrusted data; enforce policy in backend for every call |
| Scope creep | Freeze P0 list early; defer P1/P2 when delivery risk rises |
| Live demo failure | Seed demo dataset, rehearse on deployed infrastructure, record a backup |
| Claims exceed demonstrated controls | Maintain a checklist mapping every public claim to a reproducible test |

**Still to verify:** exact Token Factory model IDs/quotas; Hermes tool integration; OpenShell compatibility and isolation; Nebius scheduling/worker limits; final hackathon submission requirements and deadline; final Cortexstone domain/organization/bot availability.

## 13. Track alignment

| Track need | Cortexstone response |
|---|---|
| Always-on assistant | Deployed service plus durable scheduler/workers |
| Persistent memory | Three-layer memory, temporal retrieval, source references, edit/forget controls |
| Reusable skills | Agent-proposed skills activated only after user approval |
| User-chosen tools | Explicit connectors and per-tool permissions |
| NVIDIA open model | Eligible NVIDIA open model served through Nebius Token Factory, verified at deployment |
| Security and user control | Central policy, sandbox, approval gates, secret redaction, audit history |

## Final product definition

**Cortexstone helps users stop re-explaining context, stop manually coordinating repeatable work, and stop blindly trusting AI actions.** It combines persistent verifiable memory, reliable workflow execution, and a policy-controlled trust layer under one assistant.
