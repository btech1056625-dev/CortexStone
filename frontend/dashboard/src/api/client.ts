import { seedFindings, seedJobs, seedMemories } from './mock-data';
import type {
  ActionValidation, Api, CalendarEvent, ChatResponse, CreateMemory, DataMode, DemoScenario, Failure, GitHubIssue,
  GitHubPullRequest, GitHubRepository, GitHubWorkflowRun, HealthSnapshot, MemoryRecord, Note,
  PolicyCheck, Principal, Probe, ProposedAction, Result,
} from './types';
import { API_PATHS } from '../config';

const TIMEOUT_MS = 8000;

function kindFor(status: number): Failure['kind'] {
  if (status === 401) return 'unauthenticated';
  if (status === 403) return 'forbidden';
  if (status === 404 || status === 405 || status === 501 || status === 503) return 'unavailable';
  if (status === 429) return 'rate_limited';
  if (status >= 500) return 'server';
  return 'invalid';
}

/** One place for HTTP. Only the server's envelope message is surfaced; raw bodies and stack traces never are. */
async function call<T>(base: string, path: string, init?: RequestInit): Promise<Result<T>> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(base + path, { ...init, signal: ctl.signal, headers: { 'Content-Type': 'application/json', ...init?.headers } });
    const body: unknown = await res.json().catch(() => null);
    if (res.ok) return { ok: true, data: body as T };
    const env = body as {
      error?: { code?: unknown; message?: unknown; details?: unknown; request_id?: unknown };
      request_id?: unknown;
    } | null;
    const message = typeof env?.error?.message === 'string' ? env.error.message : 'The request could not be completed.';
    const requestId = typeof env?.error?.request_id === 'string' ? env.error.request_id
      : typeof env?.request_id === 'string' ? env.request_id : res.headers.get('X-Request-ID') ?? undefined;
    const code = typeof env?.error?.code === 'string' ? env.error.code : undefined;
    return { ok: false, kind: kindFor(res.status), message, code, details: env?.error?.details, status: res.status, requestId };
  } catch {
    return { ok: false, kind: 'network', message: 'Could not reach the API. Check that the backend is running and the base URL is correct.' };
  } finally {
    clearTimeout(timer);
  }
}

const notRegistered = (what: string): Failure => ({
  ok: false, kind: 'unavailable', message: `${what} is not registered on the backend yet, so the dashboard does not call it.`,
});
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));
const hash = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('');
const repoPath = (repo: string) => repo.split('/').map(encodeURIComponent).join('/');

export function createApi(mode: DataMode, base: string, scenario: DemoScenario = 'normal'): Api {
  const checks: PolicyCheck[] = [];
  const recordCheck = (action: ProposedAction, result: ActionValidation) => {
    checks.unshift({ action, result, at: new Date().toISOString() });
    checks.splice(8);
    return { ok: true, data: result } as const;
  };
  const recentPolicyChecks = () => checks.map((check) => ({ ...check, action: { ...check.action, arguments: { ...check.action.arguments } }, result: { ...check.result } }));

  if (mode === 'live') {
    const probe = async (path: string): Promise<Probe> => {
      const t = performance.now();
      const r = await call<unknown>(base, path);
      const ms = Math.round(performance.now() - t);
      if (r.ok) return { state: 'ok', ms };
      if (r.kind === 'network') return { state: 'unreachable', detail: r.message };
      return { state: 'degraded', ms, detail: r.status === 503 ? 'Not ready: a required dependency is unavailable.' : r.message };
    };
    const validateAction = async (action: ProposedAction) => {
      const r = await call<ActionValidation>(base, API_PATHS.validateAction, { method: 'POST', body: JSON.stringify({ action }) });
      return r.ok ? recordCheck(action, r.data) : r;
    };
    return {
      mode,
      support: { health: 'live', actions: 'live', chat: 'unavailable', memory: 'live', jobs: 'unavailable', guardian: 'unavailable', integrations: 'live' },
      async health() {
        const [health, ready, me] = await Promise.all([
          probe(API_PATHS.health), probe(API_PATHS.ready),
          (async () => {
            const t = performance.now();
            const result = await call<Principal>(base, API_PATHS.principal);
            return { result, ms: Math.round(performance.now() - t) };
          })(),
        ]);
        const principalCheck: Probe = me.result.ok
          ? { state: 'ok', ms: me.ms }
          : me.result.kind === 'network'
            ? { state: 'unreachable', detail: me.result.message }
            : { state: 'degraded', ms: me.ms, detail: me.result.message };
        return { ok: true, data: {
          health, ready, principalCheck,
          principal: me.result.ok ? me.result.data : null,
          checkedAt: new Date().toISOString(), simulated: false,
        } satisfies HealthSnapshot };
      },
      validateAction,
      recentPolicyChecks,
      sendChat: async () => notRegistered('POST /api/v1/chat'),
      listMemories: () => call<MemoryRecord[]>(base, API_PATHS.memories),
      createMemory: (memory: CreateMemory) => call<MemoryRecord>(base, API_PATHS.memories, { method: 'POST', body: JSON.stringify(memory) }),
      forgetMemory: (id) => call<void>(base, `${API_PATHS.memories}/${encodeURIComponent(id)}`, { method: 'DELETE' }),
      listJobs: async () => notRegistered('A jobs endpoint'),
      listFindings: async () => notRegistered('A findings endpoint'),
      listGithubRepos: () => call<GitHubRepository[]>(base, API_PATHS.githubRepos),
      listGithubIssues: (repo) => call<GitHubIssue[]>(base, `${API_PATHS.githubRepos}/${repoPath(repo)}/issues`),
      listGithubPulls: (repo) => call<GitHubPullRequest[]>(base, `${API_PATHS.githubRepos}/${repoPath(repo)}/pulls`),
      listGithubRuns: (repo) => call<GitHubWorkflowRun[]>(base, `${API_PATHS.githubRepos}/${repoPath(repo)}/runs`),
      listCalendarEvents: (start, end, timezone) => call<CalendarEvent[]>(base, `${API_PATHS.calendarEvents}?${new URLSearchParams({ start, end, timezone })}`),
      listNotes: () => call<Note[]>(base, API_PATHS.notes),
      createNote: (title, content) => call<Note>(base, API_PATHS.notes, { method: 'POST', body: JSON.stringify({ title, content }) }),
      updateNote: (id, title, content) => call<Note>(base, `${API_PATHS.notes}/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ title, content }) }),
      deleteNote: (id) => call<void>(base, `${API_PATHS.notes}/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    };
  }

  const ok = (ms: number): Probe => ({ state: 'ok', ms });
  const memories = seedMemories();
  const notes: Note[] = [
    { id: 'note_001', title: 'MVP principles', content: 'Policy validation never executes an action. GitHub and Calendar stay read-only.', created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    { id: 'note_002', title: 'Review queue', content: 'Check pending policy decisions before the next demo.', created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  ];
  const repos: GitHubRepository[] = [{ full_name: 'octo-org/sample-repo', name: 'sample-repo', owner: 'octo-org', private: false }];
  const calendarEvents: CalendarEvent[] = [
    { id: 'event_001', summary: 'Platform team sync', start: new Date(Date.now() + 3_600_000).toISOString(), end: new Date(Date.now() + 5_400_000).toISOString(), timezone: 'Asia/Kolkata' },
  ];
  const requireApproval = (reason: ActionValidation['reason'] = 'approval_required'): ActionValidation => ({ status: 'require_approval', reason, action_hash: hash(), risk: 'medium' });
  const mockActionResult = (action: ProposedAction): ActionValidation => {
    switch (action.tool_name) {
      case 'github.read_workflow_runs':
        return { status: 'allow', reason: 'allowed', action_hash: hash(), risk: 'low' };
      case 'notes.delete':
      case 'notes.update':
        return requireApproval();
      default:
        return { status: 'deny', reason: 'unknown_tool', action_hash: null, risk: null };
    }
  };
  const mockApi: Api = {
    mode,
    support: { health: 'simulated', actions: 'simulated', chat: 'simulated', memory: 'simulated', jobs: 'simulated', guardian: 'simulated', integrations: 'simulated' },
    async health() {
      await delay(200);
      return { ok: true, data: {
        health: ok(4), ready: ok(11), principalCheck: ok(7),
        principal: { id: 'demo-user', display_name: 'Demo operator', authenticated: true },
        checkedAt: new Date().toISOString(), simulated: true,
      } };
    },
    async validateAction(action) {
      await delay(350);
      return recordCheck(action, mockActionResult(action));
    },
    recentPolicyChecks,
    async sendChat(message, conversationId): Promise<Result<ChatResponse>> {
      await delay(900);
      if (message.startsWith('/fail')) return { ok: false, kind: 'network', message: 'Simulated network failure. Retry to continue.' };
      const wantsAction = /delete|remove|clean/i.test(message);
      return { ok: true, data: {
        conversation_id: conversationId ?? 'sim-' + hash().slice(0, 8),
        answer: wantsAction
          ? 'I can delete that note. Because it is a destructive action, I am proposing it rather than doing it. It needs policy validation and your approval first.'
          : 'This is a simulated reply. In live mode the assistant answer appears here, kept separate from any proposed actions.',
        proposed_actions: wantsAction ? [{ action_id: crypto.randomUUID(), tool_name: 'notes.delete', target_ref: 'note_001', arguments: { reason: 'User requested cleanup' }, purpose: 'Delete the note you mentioned.', requested_at: new Date().toISOString() }] : [],
      } };
    },
    async listMemories() { await delay(300); return { ok: true, data: memories.map((m) => ({ ...m })) }; },
    async createMemory(memory) {
      await delay(180);
      const created: MemoryRecord = {
        id: `m_${crypto.randomUUID()}`, content: memory.content, kind: memory.kind,
        source: 'User', inferred: false, confidence: 1, createdAt: new Date().toISOString(),
      };
      memories.unshift(created);
      return { ok: true, data: { ...created } };
    },
    async forgetMemory(id) {
      await delay(400);
      const i = memories.findIndex((m) => m.id === id);
      if (i < 0) return { ok: false, kind: 'invalid', message: 'That memory no longer exists.' };
      memories.splice(i, 1);
      return { ok: true, data: undefined };
    },
    async listJobs() { await delay(300); return { ok: true, data: seedJobs() }; },
    async listFindings() { await delay(300); return { ok: true, data: seedFindings() }; },
    async listGithubRepos() { await delay(180); return { ok: true, data: repos.map((repo) => ({ ...repo })) }; },
    async listGithubIssues() { await delay(240); return { ok: true, data: [{ number: 14, title: 'Tighten API response validation', state: 'open' }] }; },
    async listGithubPulls() { await delay(240); return { ok: true, data: [{ number: 18, title: 'Add connector read views', state: 'open', draft: false }] }; },
    async listGithubRuns() { await delay(240); return { ok: true, data: [{ id: 103, name: 'CI', status: 'completed', conclusion: 'success', created_at: new Date().toISOString() }] }; },
    async listCalendarEvents() { await delay(200); return { ok: true, data: calendarEvents.map((event) => ({ ...event })) }; },
    async listNotes() { await delay(160); return { ok: true, data: notes.map((note) => ({ ...note })) }; },
    async createNote(title, content) {
      await delay(180);
      const now = new Date().toISOString();
      const note = { id: `note_${crypto.randomUUID()}`, title, content, created_at: now, updated_at: now };
      notes.unshift(note);
      return { ok: true, data: { ...note } };
    },
    async updateNote(id, title, content) {
      await delay(180);
      const note = notes.find((item) => item.id === id);
      if (!note) return { ok: false, kind: 'invalid', message: 'That note no longer exists.' };
      note.title = title;
      note.content = content;
      note.updated_at = new Date().toISOString();
      return { ok: true, data: { ...note } };
    },
    async deleteNote(id) {
      await delay(180);
      const index = notes.findIndex((item) => item.id === id);
      if (index < 0) return { ok: false, kind: 'invalid', message: 'That note no longer exists.' };
      notes.splice(index, 1);
      return { ok: true, data: undefined };
    },
  };
  if (scenario === 'normal') return mockApi;

  const scenarioFailure = (selected: DemoScenario): Failure => {
    if (selected === 'unauthenticated') return { ok: false, kind: 'unauthenticated', status: 401, code: 'unauthenticated', message: 'Sign in to continue.' };
    if (selected === 'forbidden') return { ok: false, kind: 'forbidden', status: 403, code: 'forbidden', message: 'Your account cannot access this resource.' };
    if (selected === 'reauth') return { ok: false, kind: 'unauthenticated', status: 401, code: 'reauthentication_required', message: 'Reconnect your account to continue.' };
    return { ok: false, kind: 'unavailable', status: 503, code: 'service_unavailable', message: 'The backend is currently unavailable.' };
  };
  const gate = async <T,>(operation: () => Promise<Result<T>>): Promise<Result<T>> => {
    if (scenario !== 'empty' && scenario !== 'loading') return scenarioFailure(scenario);
    if (scenario === 'loading') await delay(15000);
    const result = await operation();
    if (scenario === 'empty' && result.ok && Array.isArray(result.data)) return { ok: true, data: [] as T };
    return result;
  };
  return {
    ...mockApi,
    health: async () => {
      if (scenario === 'loading') await delay(15000);
      const result = await mockApi.health();
      if (!result.ok || scenario === 'empty' || scenario === 'loading') return result;
      const unavailable = scenario === 'outage';
      const state: Probe['state'] = unavailable ? 'unreachable' : 'degraded';
      const detail = scenarioFailure(scenario).message;
      return { ok: true, data: {
        ...result.data,
        health: { state, detail },
        ready: { state, detail },
        principalCheck: { state, detail },
        principal: null,
      } };
    },
    validateAction: (action) => gate(() => mockApi.validateAction(action)),
    sendChat: (message, conversationId) => gate(() => mockApi.sendChat(message, conversationId)),
    listMemories: () => gate(mockApi.listMemories),
    createMemory: (memory) => gate(() => mockApi.createMemory(memory)),
    forgetMemory: (id) => gate(() => mockApi.forgetMemory(id)),
    listJobs: () => gate(mockApi.listJobs),
    listFindings: () => gate(mockApi.listFindings),
    listGithubRepos: () => gate(mockApi.listGithubRepos),
    listGithubIssues: (repo) => gate(() => mockApi.listGithubIssues(repo)),
    listGithubPulls: (repo) => gate(() => mockApi.listGithubPulls(repo)),
    listGithubRuns: (repo) => gate(() => mockApi.listGithubRuns(repo)),
    listCalendarEvents: (start, end, timezone) => gate(() => mockApi.listCalendarEvents(start, end, timezone)),
    listNotes: () => gate(mockApi.listNotes),
    createNote: (title, content) => gate(() => mockApi.createNote(title, content)),
    updateNote: (id, title, content) => gate(() => mockApi.updateNote(id, title, content)),
    deleteNote: (id) => gate(() => mockApi.deleteNote(id)),
  };
}
