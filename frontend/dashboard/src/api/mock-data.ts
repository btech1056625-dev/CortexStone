import type { Finding, JobRecord, MemoryRecord } from './types';

const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

export const seedMemories = (): MemoryRecord[] => [
  { id: 'm1', content: 'Prefers Python for backend APIs and TypeScript for the dashboard.', kind: 'fact', source: 'You, in chat', inferred: false, confidence: 1, createdAt: ago(72) },
  { id: 'm2', content: 'Working toward the CortexStone MVP demo on 30 October.', kind: 'fact', source: 'You, in chat', inferred: false, confidence: 1, createdAt: ago(50) },
  { id: 'm3', content: 'Likely prefers short bullet summaries over long prose.', kind: 'fact', source: 'Inferred from 6 conversations', inferred: true, confidence: 0.62, createdAt: ago(30) },
  { id: 'm4', content: 'Reviewed the memory API spec and flagged that PATCH is missing.', kind: 'episode', source: 'Chat session', inferred: false, confidence: 0.9, createdAt: ago(20) },
  { id: 'm5', content: 'Usually asks for a diff summary before approving a pull request.', kind: 'skill', source: 'Inferred from GitHub activity', inferred: true, confidence: 0.48, createdAt: ago(8) },
  { id: 'm6', content: 'Meets the platform team on Tuesdays at 10:00 IST.', kind: 'fact', source: 'Calendar (simulated)', inferred: true, confidence: 0.7, createdAt: ago(5) },
];

export const seedJobs = (): JobRecord[] => [
  { id: 'j1', name: 'Morning brief', status: 'succeeded', startedAt: ago(26), durationS: 14, attempts: 1, outcome: 'Summarized 3 open pull requests and 2 calendar events.' },
  { id: 'j2', name: 'Sync GitHub issues', status: 'running', startedAt: ago(0.1), durationS: null, attempts: 1, outcome: 'In progress. No result yet.' },
  { id: 'j3', name: 'Review workflow runs', status: 'awaiting_approval', startedAt: ago(1), durationS: null, attempts: 1, outcome: 'Policy validation only. No workflow action was executed.' },
  { id: 'j4', name: 'Refresh calendar cache', status: 'retry_wait', startedAt: ago(2), durationS: 31, attempts: 2, outcome: 'Provider timed out. Next retry is scheduled.' },
  { id: 'j5', name: 'Weekly memory review', status: 'failed', startedAt: ago(40), durationS: 9, attempts: 3, outcome: 'Failed after 3 attempts: the database was unavailable.' },
  { id: 'j6', name: 'Import notes', status: 'cancelled', startedAt: ago(60), durationS: 4, attempts: 1, outcome: 'Cancelled by you before any notes were imported.' },
  { id: 'j7', name: 'Nightly digest', status: 'queued', startedAt: ago(0.02), durationS: null, attempts: 0, outcome: 'Queued. Has not started.' },
];

export const seedFindings = (): Finding[] => [
  { id: 'f1', severity: 'critical', title: 'Possible access token committed to source', resource: 'octo-org/sample-repo · config/dev.py:14', detail: 'A string matching a GitHub token pattern was found (shown redacted: ghp_••••••••). Rotate the token and remove it from history.', status: 'open', foundAt: ago(3) },
  { id: 'f2', severity: 'high', title: 'Workflow runs untrusted pull request code with secrets', resource: 'octo-org/sample-repo · .github/workflows/ci.yml', detail: 'The workflow uses pull_request_target and checks out the PR head. Restrict permissions or avoid exposing secrets to forked code.', status: 'open', foundAt: ago(9) },
  { id: 'f3', severity: 'medium', title: 'Dependency with a known vulnerability', resource: 'octo-org/sample-repo · requirements.txt', detail: 'A pinned dependency has a published advisory. Upgrade to a patched release.', status: 'open', foundAt: ago(27) },
  { id: 'f4', severity: 'low', title: 'Broad token scope on connector', resource: 'Google Calendar connector', detail: 'The granted scopes exceed what read-only access needs. Reauthorize with the minimum scope.', status: 'resolved', foundAt: ago(80) },
];
