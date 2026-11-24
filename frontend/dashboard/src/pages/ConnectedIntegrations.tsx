import { useEffect, useState, type FormEvent } from 'react';
import { CalendarDays, Github, Link2, Trash2, Unlink } from 'lucide-react';
import { API_BASE, api, useHealth } from '../app-context';
import type {
  CalendarEvent,
  CalendarEventCreate,
  CalendarEventUpdate,
  CalendarWriteApproval,
  CalendarWriteResult,
  Failure,
  GitHubIssue,
  OAuthConnection,
  OAuthProvider,
  Result,
} from '../api/types';
import { ConfirmDialog } from '../dialog';
import { LoadError, Loading } from '../states';
import { Badge, Empty, PageHeader } from '../ui';
import { useToast } from '../toast';

const TIME_ZONE = 'Asia/Kolkata';

type PendingWrite = {
  approvalId: string;
  description: string;
  execute: () => Promise<Result<CalendarWriteResult | void>>;
};

function localDate(offsetDays: number): string {
  const date = new Date(Date.now() + offsetDays * 86_400_000);
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(date);
  const value = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? '';
  return `${value('year')}-${value('month')}-${value('day')}`;
}

function localDateTime(value: string): string {
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date);
  const valueOf = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? '';
  return `${valueOf('year')}-${valueOf('month')}-${valueOf('day')}T${valueOf('hour')}:${valueOf('minute')}`;
}

function providerLabel(provider: OAuthProvider): string {
  return provider === 'google' ? 'Google' : 'GitHub';
}

function isApproval(result: CalendarWriteResult | void): result is CalendarWriteApproval {
  return !!result && 'status' in result && result.status === 'approval_required';
}

function toApiDateTime(value: string): string {
  return new Date(`${value}:00+05:30`).toISOString();
}

function callbackApiOrigin(): string {
  const configured = import.meta.env.VITE_OAUTH_API_ORIGIN as string | undefined;
  if (configured) return new URL(configured).origin;
  if (API_BASE) return new URL(API_BASE).origin;
  if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
    return 'http://localhost:8000';
  }
  return location.origin;
}

export default function ConnectedIntegrations() {
  const toast = useToast();
  const { mode, accessToken } = useHealth();
  const [providers, setProviders] = useState<OAuthProvider[]>([]);
  const [connections, setConnections] = useState<OAuthConnection[]>([]);
  const [connectionError, setConnectionError] = useState<Failure | null>(null);
  const [connectionsLoading, setConnectionsLoading] = useState(true);
  const [busyProvider, setBusyProvider] = useState<OAuthProvider | null>(null);

  const [startDate, setStartDate] = useState(localDate(0));
  const [endDate, setEndDate] = useState(localDate(7));
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [calendarError, setCalendarError] = useState<Failure | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [eventTitle, setEventTitle] = useState('');
  const [eventStart, setEventStart] = useState('');
  const [eventEnd, setEventEnd] = useState('');
  const [savingEvent, setSavingEvent] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<CalendarEvent | null>(null);
  const [deletingEvent, setDeletingEvent] = useState(false);
  const [pendingWrite, setPendingWrite] = useState<PendingWrite | null>(null);
  const [approvingWrite, setApprovingWrite] = useState(false);
  const [githubRepository, setGithubRepository] = useState('');
  const [githubIssueNumber, setGithubIssueNumber] = useState(1);
  const [githubIssue, setGithubIssue] = useState<GitHubIssue | null>(null);
  const [githubIssueError, setGithubIssueError] = useState<Failure | null>(null);

  async function loadConnections() {
    setConnectionsLoading(true);
    const signedIn = mode === 'mock' || Boolean(accessToken);
    const [available, connected] = await Promise.all([
      api.oauthProviders(),
      signedIn ? api.oauthConnections() : Promise.resolve(null),
    ]);
    setConnectionsLoading(false);
    if (available.ok) setProviders(available.data.providers);
    const availabilityError = available.ok ? null : available;
    if (connected === null) {
      setConnections([]);
      setConnectionError(availabilityError);
    } else if (connected.ok) {
      setConnections(connected.data);
      setConnectionError(availabilityError);
    } else {
      setConnectionError(connected);
    }
  }

  const googleConnected = connections.some((connection) => connection.provider === 'google' && connection.connected);

  async function loadEvents() {
    setCalendarLoading(true);
    setCalendarError(null);
    const start = toApiDateTime(`${startDate}T00:00`);
    const end = toApiDateTime(`${endDate}T23:59`);
    const result = await api.listCalendarEvents(start, end, TIME_ZONE);
    setCalendarLoading(false);
    if (!result.ok) {
      setCalendarError(result);
      return;
    }
    setEvents(result.data);
    setSelectedEvent((current) => result.data.find((event) => event.id === current?.id) ?? null);
  }

  useEffect(() => { void loadConnections(); }, [accessToken, mode]);
  useEffect(() => {
    if (googleConnected) void loadEvents();
    else {
      setEvents([]);
      setCalendarError(null);
      setCalendarLoading(false);
    }
  }, [accessToken, startDate, endDate, mode, googleConnected]);

  function chooseEvent(event: CalendarEvent) {
    setSelectedEvent(event);
    setEventTitle(event.summary ?? '');
    setEventStart(localDateTime(event.start));
    setEventEnd(localDateTime(event.end));
  }

  function clearEventForm() {
    setSelectedEvent(null);
    setEventTitle('');
    setEventStart('');
    setEventEnd('');
  }

  async function finishWrite(
    result: Result<CalendarWriteResult | void>,
    description: string,
    execute: () => Promise<Result<CalendarWriteResult | void>>,
  ) {
    if (!result.ok) {
      toast('bad', `Calendar action failed. ${result.message}`);
      return;
    }
    if (isApproval(result.data)) {
      setPendingWrite({ approvalId: result.data.approval_id, description, execute });
      return;
    }
    toast('ok', description);
    setDeleteTarget(null);
    clearEventForm();
    await loadEvents();
  }

  async function saveEvent() {
    if (savingEvent || !eventTitle.trim() || !eventStart || !eventEnd) return;
    setSavingEvent(true);
    const idempotencyKey = crypto.randomUUID();
    const createPayload: CalendarEventCreate = {
      summary: eventTitle.trim(),
      start: toApiDateTime(eventStart),
      end: toApiDateTime(eventEnd),
      time_zone: TIME_ZONE,
    };
    const updatePayload: CalendarEventUpdate = {
      summary: eventTitle.trim(),
      start: createPayload.start,
      end: createPayload.end,
      time_zone: TIME_ZONE,
    };
    const description = selectedEvent ? 'Update Calendar event' : 'Create Calendar event';
    const execute = () => selectedEvent
      ? api.updateCalendarEvent(selectedEvent.id, updatePayload, idempotencyKey)
      : api.createCalendarEvent(createPayload, idempotencyKey);
    await finishWrite(await execute(), description, execute);
    setSavingEvent(false);
  }

  async function deleteEvent() {
    if (!deleteTarget || deletingEvent) return;
    setDeletingEvent(true);
    const idempotencyKey = crypto.randomUUID();
    const execute = () => api.deleteCalendarEvent(deleteTarget.id, idempotencyKey);
    await finishWrite(await execute(), 'Delete Calendar event', execute);
    setDeletingEvent(false);
  }

  async function approveAndExecute() {
    if (!pendingWrite || approvingWrite) return;
    setApprovingWrite(true);
    const approval = await api.decideApproval(pendingWrite.approvalId, 'approved');
    if (!approval.ok) {
      setApprovingWrite(false);
      toast('bad', `Could not approve Calendar action. ${approval.message}`);
      return;
    }
    const execute = pendingWrite.execute;
    const description = pendingWrite.description;
    setPendingWrite(null);
    await finishWrite(await execute(), description, execute);
    setApprovingWrite(false);
  }

  async function connectProvider(provider: OAuthProvider) {
    if (busyProvider) return;
    if (mode === 'mock') {
      const simulated = await api.connectOAuthProvider(provider, location.origin);
      if (!simulated.ok) {
        toast('bad', `Could not connect ${providerLabel(provider)}. ${simulated.message}`);
        return;
      }
      toast('ok', `Simulated ${providerLabel(provider)} connection.`);
      await loadConnections();
      return;
    }
    const popup = window.open('about:blank', `cortexstone-${provider}-connect`, 'popup,width=520,height=680');
    if (!popup) {
      toast('bad', 'Allow popups to connect an account.');
      return;
    }
    setBusyProvider(provider);
    const result = await api.connectOAuthProvider(provider, location.origin);
    if (!result.ok) {
      popup.close();
      setBusyProvider(null);
      toast('bad', `Could not start ${providerLabel(provider)} connection. ${result.message}`);
      return;
    }
    popup.location.href = result.data.authorization_url;
    const timeout = window.setTimeout(() => {
      window.removeEventListener('message', receive);
      popup.close();
      setBusyProvider(null);
      toast('bad', 'Provider connection timed out. Please try again.');
    }, 120_000);
    const receive = (event: MessageEvent<{ type?: string; provider?: string; mode?: string }>) => {
      if (event.source !== popup || event.origin !== callbackApiOrigin()) return;
      if (event.data?.type === 'cortexstone-oauth-success'
        && event.data.provider === provider && event.data.mode === 'connect') {
        window.removeEventListener('message', receive);
        clearTimeout(timeout);
        popup.close();
        setBusyProvider(null);
        toast('ok', `${providerLabel(provider)} connected.`);
        void loadConnections();
      } else if (event.data?.type === 'cortexstone-oauth-error') {
        window.removeEventListener('message', receive);
        clearTimeout(timeout);
        popup.close();
        setBusyProvider(null);
        toast('bad', `${providerLabel(provider)} connection was not completed.`);
      }
    };
    window.addEventListener('message', receive);
  }

  async function disconnectProvider(provider: OAuthProvider) {
    const result = await api.disconnectOAuthProvider(provider);
    if (!result.ok) {
      toast('bad', `Could not disconnect ${providerLabel(provider)}. ${result.message}`);
      return;
    }
    toast('ok', `${providerLabel(provider)} disconnected.`);
    await loadConnections();
    if (provider === 'google') {
      setEvents([]);
      clearEventForm();
    }
  }

  async function loadGitHubIssue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = await api.getGithubIssue(githubRepository.trim(), githubIssueNumber);
    setGithubIssue(result.ok ? result.data : null);
    setGithubIssueError(result.ok ? null : result);
  }

  const connectionFor = (provider: OAuthProvider) => connections.find((item) => item.provider === provider);

  return (
    <div className="page integrations-page">
      <PageHeader title="Connected accounts" sub="Provider access is per-user; Calendar writes need an explicit approval." />

      <section className="connector-studio-cards" aria-label="Provider connections">
        {(['google', 'github'] as const).map((provider) => {
          const connection = connectionFor(provider);
          const configured = providers.includes(provider);
          const connected = connection?.connected === true;
          const Icon = provider === 'google' ? CalendarDays : Github;
          return (
            <article className="connector-studio-card" key={provider}>
              <header><strong><Icon size={14} /> {provider === 'google' ? 'Google Calendar' : 'GitHub'}</strong>
                <Badge tone={connected ? 'ok' : 'neutral'}>{connected ? 'CONNECTED' : configured ? 'NOT CONNECTED' : 'NOT CONFIGURED'}</Badge>
              </header>
              <p>{provider === 'google'
                ? 'Primary calendar · event reads and approved writes'
                : 'GitHub App · Issues read-only for configured repositories'}</p>
              <footer>
                <span className={connectionError ? 'readonly' : 'connected'}>
                  {connectionsLoading ? 'CHECKING' : connection?.display_name ?? (connected ? 'ACCOUNT LINKED' : '')}
                </span>
                {connected
                  ? <button className="btn" onClick={() => void disconnectProvider(provider)}><Unlink size={14} />Disconnect</button>
                  : <button className="btn" disabled={!configured || !accessToken || busyProvider !== null} onClick={() => void connectProvider(provider)}>
                    <Link2 size={14} />{busyProvider === provider ? 'Connecting…' : `Connect ${providerLabel(provider)}`}
                  </button>}
              </footer>
            </article>
          );
        })}
      </section>
      {connectionError && <p role="alert" className="integration-note">{connectionError.message}</p>}
      {!accessToken && <p className="integration-note">Sign in with Google or GitHub in Settings to use connected accounts.</p>}

      <section className="panel bento-card connector-view" aria-labelledby="github-view-title">
        <header className="bento-heading">
          <div><span className="eyebrow">GITHUB APP · ISSUES READ ONLY</span><h2 id="github-view-title">Read an issue</h2></div>
          <Badge>Read-only</Badge>
        </header>
        <form className="explorer-toolbar" onSubmit={(event) => void loadGitHubIssue(event)}>
          <label htmlFor="github-repository">Repository</label>
          <input id="github-repository" value={githubRepository} onChange={(event) => setGithubRepository(event.target.value)} placeholder="owner/repository" required />
          <label htmlFor="github-issue-number">Issue</label>
          <input id="github-issue-number" value={githubIssueNumber} onChange={(event) => setGithubIssueNumber(Number(event.target.value))} type="number" min="1" step="1" required />
          <button className="btn" type="submit" disabled={!connectionFor('github')?.connected}>Read issue</button>
        </form>
        {githubIssueError && <LoadError error={githubIssueError} onRetry={() => void api.getGithubIssue(githubRepository.trim(), githubIssueNumber).then((result) => { setGithubIssue(result.ok ? result.data : null); setGithubIssueError(result.ok ? null : result); })} />}
        {githubIssue && <div className="integration-note">#{githubIssue.number} · {githubIssue.title} · {githubIssue.state}</div>}
        <p className="integration-note">The GitHub App must be installed on the repository, and the repository must be in the server allowlist.</p>
      </section>

      <section className="panel bento-card connector-view" aria-labelledby="calendar-view-title">
        <header className="bento-heading">
          <div><span className="eyebrow">GOOGLE CALENDAR · PRIMARY</span><h2 id="calendar-view-title">Calendar events</h2></div>
          <Badge>{connectionFor('google')?.connected ? 'Connected' : 'Requires Google'}</Badge>
        </header>
        <div className="explorer-toolbar date-toolbar">
          <div className="field"><label htmlFor="calendar-start">Start</label><input id="calendar-start" type="date" value={startDate} onChange={(event) => { setStartDate(event.target.value); if (endDate < event.target.value) setEndDate(event.target.value); }} /></div>
          <div className="field"><label htmlFor="calendar-end">End</label><input id="calendar-end" type="date" value={endDate} min={startDate} onChange={(event) => setEndDate(event.target.value)} /></div>
          <span className="timezone-label">TIMEZONE <code>{TIME_ZONE}</code></span>
          <button className="btn" onClick={() => void loadEvents()} disabled={!connectionFor('google')?.connected || calendarLoading}>Refresh</button>
        </div>
        {calendarLoading ? <Loading what="Calendar events" />
          : calendarError ? <LoadError error={calendarError} onRetry={() => void loadEvents()} />
            : events.length === 0 ? <Empty title="No events in this range">No Calendar events were returned for this period.</Empty>
              : <ul className="explorer-list calendar-list">
                {events.map((event) => (
                  <li key={event.id}>
                    <button className="btn" onClick={() => chooseEvent(event)}>{event.summary || '(Untitled event)'}</button>
                    <span className="mono">{new Date(event.start).toLocaleString(undefined, { timeZone: event.timezone || TIME_ZONE })}</span>
                    <button className="btn danger icon" aria-label={`Delete ${event.summary || 'event'}`} onClick={() => setDeleteTarget(event)}><Trash2 size={14} /></button>
                  </li>
                ))}
              </ul>}

        <form className="calendar-event-form" onSubmit={(event) => { event.preventDefault(); void saveEvent(); }}>
          <h3>{selectedEvent ? 'Update event' : 'Create event'}</h3>
          <label htmlFor="calendar-event-title">Title</label>
          <input id="calendar-event-title" value={eventTitle} onChange={(event) => setEventTitle(event.target.value)} maxLength={500} required />
          <div className="date-toolbar">
            <div className="field"><label htmlFor="calendar-event-start">Start</label><input id="calendar-event-start" type="datetime-local" value={eventStart} onChange={(event) => setEventStart(event.target.value)} required /></div>
            <div className="field"><label htmlFor="calendar-event-end">End</label><input id="calendar-event-end" type="datetime-local" value={eventEnd} onChange={(event) => setEventEnd(event.target.value)} required /></div>
          </div>
          <footer>
            {selectedEvent && <button className="btn" type="button" onClick={clearEventForm}>Cancel edit</button>}
            <button className="btn primary" type="submit" disabled={!connectionFor('google')?.connected || savingEvent || !eventTitle.trim() || !eventStart || !eventEnd}>
              {savingEvent ? 'Saving…' : selectedEvent ? 'Update event' : 'Create event'}
            </button>
          </footer>
          <p className="integration-note">Calendar changes require policy permission and a separate approval before execution.</p>
        </form>
      </section>

      {mode === 'live' && <p className="integration-note">Cortexstone Notes is not yet available through the live API.</p>}
      <ConfirmDialog open={deleteTarget !== null} title="Delete Calendar event?" confirmLabel="Continue" busy={deletingEvent} onConfirm={() => void deleteEvent()} onCancel={() => setDeleteTarget(null)}>
        <p>This action will be submitted for policy approval before it can delete <strong>{deleteTarget?.summary || 'this event'}</strong>.</p>
      </ConfirmDialog>
      <ConfirmDialog open={pendingWrite !== null} title="Approve Calendar change?" confirmLabel="Approve and execute" busy={approvingWrite} onConfirm={() => void approveAndExecute()} onCancel={() => setPendingWrite(null)}>
        <p><strong>{pendingWrite?.description}</strong> will affect your primary calendar. Approval applies once to this exact operation.</p>
      </ConfirmDialog>
    </div>
  );
}
