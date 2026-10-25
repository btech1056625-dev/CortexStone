import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApi } from './client';

afterEach(() => vi.unstubAllGlobals());
const sample = { action_id: 'x', tool_name: 'notes.delete', target_ref: 'r', arguments: {}, purpose: '', requested_at: '' };

describe('live mode', () => {
  it('never calls the unregistered chat route', async () => {
    const f = vi.fn(); vi.stubGlobal('fetch', f);
    const r = await createApi('live', '').sendChat('hi', null);
    expect(f).not.toHaveBeenCalled();
    expect(r.ok).toBe(false);
  });
  it('maps the real 503 envelope without leaking the body', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'service_unavailable', message: 'Not configured.' }, request_id: 'r1', trace: 'SECRET' }), { status: 503 })));
    const r = await createApi('live', '').validateAction(sample);
    expect(r).toMatchObject({ ok: false, kind: 'unavailable', status: 503, requestId: 'r1', message: 'Not configured.' });
    expect(JSON.stringify(r)).not.toContain('SECRET');
  });
  it('preserves nested error details and request id for rate limits', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      error: { code: 'rate_limited', message: 'Try again later.', details: { retry_after: 12 }, request_id: 'request-42' },
    }), { status: 429 })));
    const result = await createApi('live', '').validateAction(sample);
    expect(result).toMatchObject({
      ok: false, kind: 'rate_limited', status: 429, code: 'rate_limited',
      message: 'Try again later.', details: { retry_after: 12 }, requestId: 'request-42',
    });
  });
  it('reports network failure honestly instead of falling back to mock', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('down'); }));
    const h = await createApi('live', '').health();
    expect(h.ok && h.data.health.state).toBe('unreachable');
    expect(h.ok && h.data.simulated).toBe(false);
  });
  it('probes the contract health, readiness, and authenticated-principal routes', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return new Response(JSON.stringify(url.endsWith('/api/v1/me')
        ? { id: 'user-1', display_name: 'Operator', authenticated: true }
        : { status: 'ok' }), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    const result = await createApi('live', '').health();
    expect(result.ok).toBe(true);
    expect(fetchMock.mock.calls.map(([input]) => String(input)).sort()).toEqual(['/api/v1/me', '/health', '/ready']);
    expect(result.ok && result.data.principal).toEqual({ id: 'user-1', display_name: 'Operator', authenticated: true });
  });
  it('uses the calendar contract query and notes CRUD paths', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify([]), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const live = createApi('live', '');
    await live.listCalendarEvents('2026-10-25T00:00:00+05:30', '2026-11-01T00:00:00+05:30', 'Asia/Kolkata');
    await live.listNotes();
    await live.createNote('Title', 'Body');
    await live.updateNote('note 1', 'Updated', 'Body 2');
    await live.deleteNote('note 1');
    expect(fetchMock.mock.calls.map(([input, init]) => [String(input), init?.method ?? 'GET'])).toEqual([
      ['/api/v1/connectors/calendar/events?start=2026-10-25T00%3A00%3A00%2B05%3A30&end=2026-11-01T00%3A00%3A00%2B05%3A30&timezone=Asia%2FKolkata', 'GET'],
      ['/api/v1/notes', 'GET'],
      ['/api/v1/notes', 'POST'],
      ['/api/v1/notes/note%201', 'PATCH'],
      ['/api/v1/notes/note%201', 'DELETE'],
    ]);
  });
  it('uses the repository issues, pulls, and runs read routes', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify([]), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const live = createApi('live', '');
    await live.listGithubRepos();
    await live.listGithubIssues('octo-org/sample-repo');
    await live.listGithubPulls('octo-org/sample-repo');
    await live.listGithubRuns('octo-org/sample-repo');
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      '/api/v1/connectors/github/repos',
      '/api/v1/connectors/github/repos/octo-org/sample-repo/issues',
      '/api/v1/connectors/github/repos/octo-org/sample-repo/pulls',
      '/api/v1/connectors/github/repos/octo-org/sample-repo/runs',
    ]);
  });
  it('creates memories through the contract endpoint without a browser user id', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({
      id: 'memory-1', content: 'Prefers concise summaries', kind: 'preference', source: 'user',
      inferred: false, confidence: 1, createdAt: '2026-10-30T00:00:00Z',
    }), { status: 201 }));
    vi.stubGlobal('fetch', fetchMock);
    const result = await createApi('live', '').createMemory({ content: 'Prefers concise summaries', kind: 'preference' });
    expect(result.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/memories', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ content: 'Prefers concise summaries', kind: 'preference' }),
    }));
  });
});

describe('mock mode', () => {
  it('validation reports a policy outcome, never approval or execution', async () => {
    const r = await createApi('mock', '').validateAction(sample);
    expect(r.ok && r.data.status).toBe('require_approval');
  });
  it('denies forbidden GitHub and Calendar write proposals', async () => {
    const mock = createApi('mock', '');
    const result = await mock.validateAction({ ...sample, tool_name: 'github.create_issue' });
    const calendar = await mock.validateAction({ ...sample, tool_name: 'calendar.create_event' });
    expect(result.ok && result.data.status).toBe('deny');
    expect(calendar.ok && calendar.data.status).toBe('deny');
  });
  it('allows the read-only workflow-run proposal without execution', async () => {
    const result = await createApi('mock', '').validateAction({ ...sample, tool_name: 'github.read_workflow_runs' });
    expect(result.ok && result.data.status).toBe('allow');
  });
});

describe('memory', () => {
  it('forgetting removes the record for the session; live mode uses the memory endpoint', async () => {
    const mock = createApi('mock', '');
    const before = await mock.listMemories();
    expect(before.ok && before.data.length).toBeGreaterThan(1);
    expect((await mock.forgetMemory('m1')).ok).toBe(true);
    const after = await mock.listMemories();
    expect(after.ok && after.data.some((m) => m.id === 'm1')).toBe(false);
    expect((await mock.forgetMemory('m1')).ok).toBe(false);
    const f = vi.fn(async () => new Response(null, { status: 204 })); vi.stubGlobal('fetch', f);
    const live = await createApi('live', '').forgetMemory('m1');
    expect(live.ok).toBe(true);
    expect(f).toHaveBeenCalledWith('/api/v1/memories/m1', expect.objectContaining({ method: 'DELETE' }));
  });

  describe('notes', () => {
    it('supports mock create, update, and delete operations', async () => {
      const mock = createApi('mock', '');
      const created = await mock.createNote('Draft', 'Initial content');
      expect(created.ok).toBe(true);
      if (!created.ok) return;
      const updated = await mock.updateNote(created.data.id, 'Reviewed draft', 'Updated content');
      expect(updated.ok && updated.data).toMatchObject({ title: 'Reviewed draft', content: 'Updated content' });
      expect((await mock.deleteNote(created.data.id)).ok).toBe(true);
      const list = await mock.listNotes();
      expect(list.ok && list.data.some((note) => note.id === created.data.id)).toBe(false);
    });
  });
});
