
# Cortexstone Design Rules

> Product: Cortexstone  
> Version: 2.0  
> Core pillars: Remember · Act · Protect  
> Purpose: Define consistent UI/UX rules for every Cortexstone interface.

## 1. Product Design Philosophy

Cortexstone is an always-on personal AI assistant for developers and everyday users. The interface must communicate three capabilities:

- **Remember:** Preserve useful context and let users inspect, correct, and forget it.
- **Act:** Help users execute workflows, monitor progress, and recover from failures.
- **Protect:** Make permissions, approvals, security findings, and action history understandable.

### Non-negotiable principles

1. Clarity over decoration.
2. Trust over artificial intelligence theatrics.
3. Useful information over visual clutter.
4. Visible control over hidden automation.
5. Consistency across the dashboard, Telegram, and future interfaces.
6. Honest status reporting; never display a successful result before it is verified.
7. Every important action must have an understandable outcome.

## 2. Visual Identity

### 2.1 Overall aesthetic

Use a professional, modern, dark-first interface with a restrained futuristic developer-tool aesthetic.

The visual language should feel:
- Technical, calm, precise, and trustworthy.
- Appropriate for developers, platform engineers, and everyday users.
- Inspired by professional developer dashboards rather than gaming interfaces.
- Consistent across desktop, tablet, and mobile.

Avoid excessive neon, glowing borders, animated backgrounds, glass effects, gradients on every card, and decorative elements that reduce readability.

### 2.2 Color tokens

Use design tokens instead of hardcoding colors throughout components.

Suggested dark theme:

| Token | Value | Purpose |
|---|---|---|
| `--bg-primary` | `#0B1020` | Main application background |
| `--bg-surface` | `#121A2B` | Cards and panels |
| `--bg-elevated` | `#19243A` | Menus and elevated surfaces |
| `--border-default` | `#29364D` | Standard borders |
| `--text-primary` | `#F1F5F9` | Primary text |
| `--text-secondary` | `#A7B4C8` | Supporting text |
| `--accent-primary` | `#55B8FF` | Primary actions and links |
| `--accent-secondary` | `#A78BFA` | Memory and AI-related accents |
| `--status-success` | `#34D399` | Verified success |
| `--status-warning` | `#FBBF24` | Warnings and pending attention |
| `--status-danger` | `#FB7185` | Errors and security risks |
| `--status-info` | `#60A5FA` | Informational status |

Color must never be the only indicator of a state. Pair status colors with text, icons, or labels.

Use gradients sparingly, primarily for brand accents or a small number of decorative highlights.

A light theme may be added later. It must use semantic tokens rather than invert dark-theme colors mechanically.

## 3. Typography

1. Use a clean, highly readable sans-serif font.
2. Use a monospaced font only for code, IDs, commands, hashes, and technical output.
3. Maintain a clear hierarchy between page titles, section titles, body text, labels, and metadata.
4. Body text should generally be 14–16 px on desktop.
5. Supporting text must remain comfortably readable; avoid tiny metadata.
6. Use consistent font weights and line heights.
7. Avoid long paragraphs in dashboards. Prefer short explanations, lists, and structured details.
8. Do not use all-uppercase text for long headings or descriptions.

Suggested hierarchy:

- Page title: 28–32 px
- Section heading: 20–24 px
- Card heading: 16–18 px
- Body text: 14–16 px
- Secondary metadata: 12–14 px

These are starting values, not reasons to violate accessibility or responsive constraints.

## 4. Layout and Spacing

1. Use a consistent spacing scale, preferably multiples of 4 px.
2. Keep page content aligned to a consistent grid.
3. Use whitespace to separate concepts and reduce cognitive load.
4. Avoid unnecessary nested cards and excessive borders.
5. Use consistent corner radii, shadows, and panel padding.
6. Prefer a responsive sidebar or compact navigation on desktop and an appropriate navigation pattern on mobile.
7. Keep primary page actions easy to find.
8. Avoid horizontal scrolling for primary workflows at supported viewport sizes.
9. Keep important information visible without forcing users to inspect multiple unrelated panels.
10. Do not make every section visually prominent; establish a clear information hierarchy.

## 5. Application Navigation

Organize the main dashboard around the product's actual capabilities.

Recommended navigation:

- **Overview:** Current status, important tasks, recent activity, and assistant brief.
- **Chat:** Conversation and assistant interaction.
- **Memory:** Search, inspect, edit, and forget remembered information.
- **Jobs & Workflows:** Scheduled tasks, workflow progress, retries, and cancellation.
- **Actions & Approvals:** Pending approvals and completed or failed tool actions.
- **Guardian:** Security scans, findings, severity, and remediation status.
- **Integrations:** Connected services, permissions, and connection health.
- **Settings:** User preferences, privacy, notifications, and account controls.

Do not expose a navigation item as functional until its core workflow exists. Clearly mark unavailable integrations or unfinished features.

## 6. Core User Experiences

### 6.1 Overview

The overview should answer:

1. What needs my attention?
2. What has Cortexstone done?
3. What is scheduled next?
4. Are there failures or security issues?
5. Is the system healthy?

Prioritize pending approvals, failed jobs, urgent security findings, and actionable tasks over decorative statistics.

Do not invent activity or display fabricated metrics.

### 6.2 Memory

The Memory interface must make stored context inspectable and user-controlled.

Each memory record should show, when available:

- The remembered fact or summary.
- Source or origin.
- Creation or observation time.
- Confidence or uncertainty, where applicable.
- Memory category and sensitivity.
- Edit and forget controls.

Rules:

1. Distinguish an explicitly stated fact from an inferred preference.
2. Never present an uncertain inference as a confirmed fact.
3. Make edit and forget actions discoverable.
4. Confirm destructive actions when appropriate.
5. Show a clear result after an edit or deletion.
6. Do not reveal another user's memory.
7. Do not expose secrets in memory previews or search results.
8. If deletion is still processing, communicate that state honestly.

### 6.3 Actions and Approvals

An approval screen must explain the proposed action before the user approves it.

Display:

- What Cortexstone proposes to do.
- Which connected service or resource will be affected.
- The target and relevant arguments or changes.
- Why the action is being proposed.
- The likely impact.
- Whether the action is reversible.
- The approval expiry, if applicable.

Provide explicit Approve and Reject controls. Use Cancel for stopping an in-progress operation where cancellation is supported.

Approval must refer to the exact proposed action. If the action, target, or material arguments change, require a new approval.

Never style an approval as a routine notification that can be dismissed without understanding its consequences.

### 6.4 Jobs and Workflows

Every job should have an explicit status:

- Queued
- Running
- Waiting for approval
- Retrying
- Succeeded
- Failed
- Cancelled

Show progress, last update, attempt count, and a concise explanation of failure when available.

Rules:

1. Do not report a job as successful until its outcome has been verified.
2. Distinguish a transient failure from a permanent failure.
3. Show when the next retry is scheduled, if known.
4. Provide cancellation only when supported by the execution layer.
5. Do not imply cancellation has completed until confirmed.
6. Preserve job history and meaningful error context without exposing secrets.
7. Offer a safe recovery or retry action where supported.

### 6.5 Guardian

Security findings should be actionable, not frightening.

Each finding should include:

- Severity and finding category.
- Affected repository or resource.
- File path or safe location reference, when available.
- Redacted evidence.
- Detection time.
- Recommended remediation.
- Current status.

Never display raw secret values. Do not place secret values in notifications, browser state, URLs, logs, or copyable diagnostic output.

Clearly distinguish a detected finding from a confirmed exploit or incident.

### 6.6 Integrations

For each integration, show:

- Connection status.
- Granted permissions and scopes.
- Last successful interaction, when known.
- Any connection error and a useful next step.
- A way to revoke access.

Never imply that an integration is connected when it is mocked, unavailable, or disconnected.

## 7. Interaction Rules

1. Every visible button must perform its advertised action.
2. Use clear labels such as `Save memory`, `Forget memory`, `Approve action`, and `Retry job`.
3. Avoid ambiguous labels such as `Continue` when the result is consequential.
4. Disable controls only when necessary and explain why when the reason is not obvious.
5. Show loading states for operations that take time.
6. Prevent accidental duplicate submissions.
7. Use confirmation dialogs for consequential or destructive actions.
8. Show success only after the backend confirms the result.
9. Show errors with a concise explanation and a recovery path when possible.
10. Preserve user input after recoverable errors.
11. Do not silently discard changes.
12. Respect reduced-motion preferences.

## 8. Accessibility

1. Use semantic HTML and accessible component patterns.
2. Support keyboard navigation for all important workflows.
3. Provide visible focus indicators.
4. Associate inputs with clear labels and helpful validation messages.
5. Ensure dialogs manage focus and can be dismissed safely.
6. Provide accessible names for icon-only controls.
7. Use adequate contrast for text, controls, borders, and focus indicators.
8. Never rely only on color to communicate severity or state.
9. Announce meaningful asynchronous status changes to assistive technology.
10. Ensure charts and visual status indicators have textual equivalents.

Target WCAG 2.2 AA where practical and validate the implemented experience rather than claiming compliance by default.

## 9. Responsive Design

- Desktop: support dense workflows without overwhelming the user.
- Tablet: preserve clear navigation and readable content.
- Mobile: prioritize the current task, approvals, notifications, and memory controls.
- Forms and dialogs must fit small screens.
- Tables should adapt into stacked records or controlled horizontal scrolling where necessary.
- Touch targets should be comfortably usable.
- Never hide a critical security warning solely because the viewport is small.

## 10. Frontend Engineering Rules

1. Reuse shared components and design tokens.
2. Keep UI components separate from API and business logic.
3. Validate forms on the client for usability and on the backend for correctness.
4. Treat all server and connector content as untrusted display data.
5. Render user-provided text safely; never interpret it as executable markup.
6. Do not store credentials or secrets in frontend source code.
7. Do not use frontend state as proof of authorization.
8. The backend is authoritative for permissions, approvals, and action status.
9. Represent loading, empty, error, and success states explicitly.
10. Avoid unnecessary dependencies and oversized component abstractions.
11. Keep reusable components typed and documented.
12. Test critical interactions, including rejection, failure, retry, and cancellation.

## 11. Empty, Error, and Offline States

Every major page must define:

- Loading state.
- Empty state.
- Success state.
- Recoverable error state.
- Permission-denied state.
- Dependency-unavailable state where relevant.

An empty page should explain what the user can do next.

An error should never silently become an empty result. Distinguish “no records found” from “records could not be loaded.”

## 12. Design Acceptance Checklist

Before a UI feature is accepted, verify:

- [ ] It follows the shared design tokens and typography.
- [ ] Its primary purpose is obvious.
- [ ] It works at supported viewport sizes.
- [ ] It has loading, empty, error, and success states.
- [ ] Keyboard and focus behavior work.
- [ ] Consequential actions show the necessary details.
- [ ] Status is consistent with backend-confirmed state.
- [ ] No secrets or cross-user data are exposed.
- [ ] The feature has been tested with realistic failure cases.
- [ ] Unimplemented functionality is not presented as complete.

## 13. Final Rule

Cortexstone should look powerful because it makes complex work understandable—not because it looks complicated.

Every screen must reinforce at least one pillar: Remember, Act, or Protect. Prefer interfaces that give users context, control, and confidence.

