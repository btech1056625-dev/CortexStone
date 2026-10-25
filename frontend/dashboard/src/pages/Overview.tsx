import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from 'react';
import { ArrowUpRight, CheckCheck, FileJson2, MessageSquareText, Radio, Search, ShieldCheck } from 'lucide-react';
import { api, useHealth } from '../app-context';
import type { CalendarEvent, Failure, GitHubRepository, MemoryRecord, Note, PolicyCheck, Result } from '../api/types';
import { ConfirmDialog, Modal } from '../dialog';
import { useToast } from '../toast';
import { Banner, BentoCard, Empty, PageHeader, fmtTime, trackSpotlight } from '../ui';

interface Feed<T> { data: T[]; error: Failure | null; loading: boolean }
const emptyFeed = <T,>(): Feed<T> => ({ data: [], error: null, loading: true });
const endpointStatus = (state?: string) => state === 'ok' ? 'Connected' : state === 'degraded' ? 'Degraded' : state === 'unreachable' ? 'Unreachable' : 'Checking';

function StatusLine({ label, path, state, detail, ms }: { label: string; path: string; state?: string; detail?: string; ms?: number }) {
  return (
    <div className="status-line">
      <span className={`status-indicator ${state ?? 'checking'}`} />
      <span className="status-name">{label}</span>
      <code>{path}</code>
      <span className={`status-text ${state ?? 'checking'}`}>{state ? endpointStatus(state) : 'Checking'}</span>
      <span className="mono latency">{ms === undefined ? '—' : `${ms} ms`}</span>
      {detail && <span className="status-detail">{detail}</span>}
      <span className="latency-track"><i style={{ width: `${ms === undefined ? 5 : Math.min(100, Math.max(8, ms / 4))}%` }} /></span>
    </div>
  );
}

export default function Overview() {
  const { snap, loading, refresh } = useHealth();
  const [prompt, setPrompt] = useState('');
  const [memories, setMemories] = useState<Feed<MemoryRecord>>(emptyFeed);
  const [repos, setRepos] = useState<Feed<GitHubRepository>>(emptyFeed);
  const [events, setEvents] = useState<Feed<CalendarEvent>>(emptyFeed);
  const [notes, setNotes] = useState<Feed<Note>>(emptyFeed);
  const [checks, setChecks] = useState<PolicyCheck[]>([]);
  const [inspect, setInspect] = useState<PolicyCheck | null>(null);
  const [forgetTarget, setForgetTarget] = useState<MemoryRecord | null>(null);
  const [forgetting, setForgetting] = useState(false);
  const toast = useToast();
  const [now] = useState(() => Date.now());
  const start = useMemo(() => new Date(now).toISOString(), [now]);
  const end = useMemo(() => new Date(now + 7 * 24 * 60 * 60 * 1000).toISOString(), [now]);

  useEffect(() => {
    const load = <T,>(promise: Promise<Result<T[]>>, setter: (value: Feed<T>) => void) => {
      void promise.then((result) => {
        if (!result.ok) { setter({ data: [], error: result, loading: false }); return; }
        if (!Array.isArray(result.data)) {
          setter({ data: [], error: { ok: false, kind: 'invalid', message: 'The API returned an unexpected list response.' }, loading: false });
          return;
        }
        setter({ data: result.data, error: null, loading: false });
      });
    };
    load(api.listMemories(), setMemories);
    load(api.listGithubRepos(), setRepos);
    load(api.listCalendarEvents(start, end, 'Asia/Kolkata'), setEvents);
    load(api.listNotes(), setNotes);
    setChecks(api.recentPolicyChecks());
  }, [start, end]);

  function openChat(event: FormEvent) {
    event.preventDefault();
    jumpToChat(prompt);
  }

  function jumpToChat(value: string) {
    const query = value.trim();
    if (!query) return;
    location.hash = `#/chat?prompt=${encodeURIComponent(query)}`;
  }

  async function forgetMemory() {
    if (!forgetTarget || forgetting) return;
    setForgetting(true);
    const result = await api.forgetMemory(forgetTarget.id);
    setForgetting(false);
    if (!result.ok) { toast('bad', `Couldn't forget this memory. ${result.message}`); return; }
    setMemories((current) => ({ ...current, data: current.data.filter((memory) => memory.id !== forgetTarget.id) }));
    setForgetTarget(null);
    toast('ok', 'Memory forgotten.');
  }

  const health = snap?.health;
  const ready = snap?.ready;
  const principalCheck = snap?.principalCheck;
  const principalState = !snap ? 'CHECKING' : snap.principal?.authenticated ? 'AUTHENTICATED' : snap.principal ? 'NOT AUTHENTICATED' : 'UNAVAILABLE';

  return (
    <div className="page overview-page">
      <PageHeader title="Operations" sub="A live read on your workspace, access, and policy boundary." />

      <form className="quick-command bento-card" onSubmit={openChat} onMouseMove={trackSpotlight}>
        <MessageSquareText size={18} aria-hidden />
        <label className="sr" htmlFor="quick-prompt">Ask Cortexstone</label>
        <input id="quick-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Ask Cortexstone anything…" />
        <span className="quick-hint"><span>OPEN CHAT</span><kbd>↵</kbd></span>
        <button className="btn primary" type="submit" disabled={!prompt.trim()}><Search size={15} />Ask <kbd>↵</kbd></button>
      </form>
      <div className="quick-chips" aria-label="Suggested prompts">
        <button className="quick-chip" onClick={() => jumpToChat("Summarize open PRs & today's calendar")}>Summarize open PRs &amp; today's calendar</button>
        <button className="quick-chip" onClick={() => jumpToChat('Validate note deletion policy')}>Validate note deletion policy</button>
      </div>

      <div className="bento-grid">
        <BentoCard className="bento-telemetry" aria-labelledby="telemetry-title">
          <header className="bento-heading"><div><span className="bento-kicker">01 / SYSTEM</span><h2 id="telemetry-title">System telemetry</h2></div><button className="btn telemetry-refresh" onClick={refresh} disabled={loading}><Radio size={14} />{loading ? 'Checking' : 'Refresh'}</button></header>
          <div className="status-stack">
            <StatusLine label="Liveness" path="/health" state={health?.state} detail={health?.detail} ms={health?.ms} />
            <StatusLine label="Readiness" path="/ready" state={ready?.state} detail={ready?.detail} ms={ready?.ms} />
            <StatusLine label="Principal" path="/api/v1/me" state={principalCheck?.state} detail={principalCheck?.detail} ms={principalCheck?.ms} />
          </div>
          <div className="principal-strip">
            <span className="principal-avatar">{snap?.principal?.display_name.slice(0, 1) ?? '—'}</span>
            <div><span className="muted">Authenticated principal</span><strong>{snap?.principal?.display_name ?? (snap ? 'Unavailable' : 'Checking…')}</strong></div>
            <code>{snap?.principal?.id ?? 'no principal'}</code>
            <span className={`principal-state ${!snap ? 'checking' : snap.principal?.authenticated ? 'ok' : 'bad'}`}>{principalState}</span>
          </div>
        </BentoCard>

        <BentoCard className="bento-connectors" aria-labelledby="connectors-title">
          <header className="bento-heading"><div><span className="bento-kicker">02 / CONNECTED SOURCES</span><h2 id="connectors-title">Connector matrix</h2></div><a className="text-link" href="#/integrations">Explore <ArrowUpRight size={14} /></a></header>
          <div className="connector-matrix">
            <a className="connector-row" href="#/integrations?tab=github"><span className="connector-mark github-mark">GH</span><div><strong>GitHub</strong><span className="connector-state">{repos.loading ? 'CHECKING' : repos.error ? 'UNAVAILABLE' : 'READ ONLY'}</span></div><span className={`connector-count ${repos.error ? 'error' : ''}`}>{repos.loading ? '—' : repos.data.length}<small>{repos.data.length === 1 ? 'repo' : 'repos'}</small></span></a>
            <a className="connector-row" href="#/integrations?tab=calendar"><span className="connector-mark calendar-mark">◷</span><div><strong>Google Calendar</strong><span className="connector-state">{events.loading ? 'CHECKING' : events.error ? 'UNAVAILABLE' : 'READ ONLY'}</span></div><span className={`connector-count ${events.error ? 'error' : ''}`}>{events.loading ? '—' : events.data.length}<small>{events.data.length === 1 ? 'event' : 'events'}</small></span></a>
            <a className="connector-row" href="#/integrations?tab=notes"><span className="connector-mark notes-mark">N</span><div><strong>Cortexstone Notes</strong><span className="connector-state">{notes.loading ? 'CHECKING' : notes.error ? 'UNAVAILABLE' : 'BUILT IN'}</span></div><span className={`connector-count ${notes.error ? 'error' : ''}`}>{notes.loading ? '—' : notes.data.length}<small>{notes.data.length === 1 ? 'note' : 'notes'}</small></span></a>
          </div>
          {(repos.error || events.error || notes.error) && <p className="connector-warning">{[repos.error, events.error, notes.error].filter(Boolean).map((error) => error?.message).join(' ')}</p>}
        </BentoCard>

        <BentoCard className="bento-policy" aria-labelledby="policy-title">
          <header className="bento-heading"><div><span className="bento-kicker">03 / POLICY</span><h2 id="policy-title">Validation checks</h2></div><a className="text-link" href="#/actions">Validate action <ArrowUpRight size={14} /></a></header>
          <p className="policy-note">Policy check only <span>·</span> proposals are never executed here</p>
          {checks.length ? <ul className="policy-list">{checks.map((check, index) => (
            <li key={check.action.action_id} style={{ '--stagger-index': index } as CSSProperties}>
              <div className="policy-icon"><ShieldCheck size={16} /></div>
              <div className="policy-main"><strong>{check.action.tool_name}</strong><span>{check.action.target_ref}</span></div>
              <span className={`policy-outcome ${check.result.status}`}>{check.result.status.replace('_', ' ')}</span>
              <button className="btn icon" onClick={() => setInspect(check)} aria-label={`Inspect ${check.action.tool_name} validation JSON`}><FileJson2 size={15} /></button>
            </li>
          ))}</ul> : <div className="policy-awaiting"><span className="awaiting-mark"><ShieldCheck size={16} /></span><strong>Awaiting action proposal</strong><span>Validate a proposal to see its policy outcome.</span><a href="#/actions">Open policy sandbox <ArrowUpRight size={13} /></a></div>}
          <div className="policy-footer"><CheckCheck size={14} /> No action is run from this view.</div>
        </BentoCard>

        <BentoCard className="bento-memory" aria-labelledby="memory-title">
          <header className="bento-heading"><div><span className="bento-kicker">04 / OWNER-SCOPED</span><h2 id="memory-title">Memory provenance</h2></div><a className="text-link" href="#/memory">All memory <ArrowUpRight size={14} /></a></header>
          {memories.loading ? <p className="body muted">Loading owner-scoped memories…</p> : memories.data.length ? <>
            <div className="memory-ticker">{memories.data.slice().sort((a, b) => b.createdAt.localeCompare(a.createdAt)).slice(0, 3).map((memory, index) => (
              <article className="memory-ticker-item" key={memory.id} style={{ '--stagger-index': index } as CSSProperties}>
                <div className="memory-ticker-meta"><span className={`source-tag ${memory.inferred ? 'inferred' : 'user'}`}>{memory.inferred ? 'INFERRED' : 'USER-STATED'}</span><span className="memory-score">{memory.confidence.toFixed(2)}</span></div>
                <p>{memory.content}</p>
                <div className="memory-segments" role="img" aria-label={`Confidence ${Math.round(memory.confidence * 100)} percent`}>{Array.from({ length: 10 }, (_, segment) => <i className={segment < Math.round(memory.confidence * 10) ? 'filled' : ''} key={segment} />)}</div>
                <div className="memory-ticker-meta"><time>{fmtTime(memory.createdAt)}</time><button className="quick-forget" onClick={() => setForgetTarget(memory)}>FORGET</button></div>
              </article>
            ))}</div>
            <div className="memory-source-bars"><span>USER {memories.data.filter((memory) => !memory.inferred).length}</span><div className="source-meter"><i className="user-segment" style={{ width: `${memories.data.length ? memories.data.filter((memory) => !memory.inferred).length / memories.data.length * 100 : 0}%` }} /><i className="inferred-segment" style={{ width: `${memories.data.length ? memories.data.filter((memory) => memory.inferred).length / memories.data.length * 100 : 0}%` }} /></div><span>INFERRED {memories.data.filter((memory) => memory.inferred).length}</span></div>
          </> : <Empty title={memories.error ? 'Memory unavailable' : 'No memories yet'}>{memories.error?.message ?? 'Owner-scoped memories will appear here with their provenance.'}</Empty>}
        </BentoCard>
      </div>

      <Modal open={inspect !== null} title="Validation payload" onClose={() => setInspect(null)}>
        {inspect && <><p className="muted modal-intro">Policy validation is not execution. This JSON stays in this browser session.</p><pre>{JSON.stringify({ action: inspect.action, validation: inspect.result, validated_at: inspect.at }, null, 2)}</pre></>}
      </Modal>
      <ConfirmDialog open={forgetTarget !== null} title="Forget this memory?" confirmLabel="Forget memory" busy={forgetting} onConfirm={() => void forgetMemory()} onCancel={() => setForgetTarget(null)}>
        <p>{forgetTarget?.content}</p><p className="muted" style={{ marginTop: 8 }}>This removes it from the owner-scoped memory store.</p>
      </ConfirmDialog>
    </div>
  );
}
