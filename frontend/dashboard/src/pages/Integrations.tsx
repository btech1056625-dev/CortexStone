import { useEffect, useMemo, useState } from 'react';
import { CalendarDays, FilePlus2, Github, NotebookPen, Save, Trash2 } from 'lucide-react';
import { api } from '../app-context';
import type { CalendarEvent, Failure, GitHubIssue, GitHubPullRequest, GitHubRepository, GitHubWorkflowRun, Note } from '../api/types';
import { ConfirmDialog } from '../dialog';
import { useToast } from '../toast';
import { LoadError, Loading } from '../states';
import { Badge, Empty, PageHeader } from '../ui';

type ConnectorTab = 'github' | 'calendar' | 'notes';
type GitHubView = 'repos' | 'issues' | 'pulls' | 'runs';

const connectorTabs: { id: ConnectorTab; label: string; icon: typeof Github }[] = [
  { id: 'github', label: 'GitHub', icon: Github },
  { id: 'calendar', label: 'Google Calendar', icon: CalendarDays },
  { id: 'notes', label: 'Cortexstone Notes', icon: NotebookPen },
];
const githubViews: { id: GitHubView; label: string }[] = [
  { id: 'repos', label: 'Repositories' },
  { id: 'issues', label: 'Issues' }, { id: 'pulls', label: 'Pull requests' }, { id: 'runs', label: 'Workflow runs' },
];
const repoDefault = 'octo-org/sample-repo';
const isoDate = (offset: number) => {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(Date.now() + offset * 24 * 60 * 60 * 1000);
  const value = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? '';
  return `${value('year')}-${value('month')}-${value('day')}`;
};

function selectedTab(): ConnectorTab {
  const raw = new URLSearchParams(location.hash.split('?')[1] ?? '').get('tab');
  return raw === 'calendar' || raw === 'notes' ? raw : 'github';
}

function describeError<T>(result: { ok: true; data: T } | Failure, setter: (failure: Failure | null) => void) {
  setter(result.ok ? null : result);
}

export default function Integrations() {
  const toast = useToast();
  const [tab, setTab] = useState<ConnectorTab>(selectedTab);
  const [githubView, setGithubView] = useState<GitHubView>('repos');
  const [repos, setRepos] = useState<GitHubRepository[]>([]);
  const [repoError, setRepoError] = useState<Failure | null>(null);
  const [repoLoading, setRepoLoading] = useState(true);
  const [repo, setRepo] = useState(repoDefault);
  const [githubData, setGithubData] = useState<(GitHubRepository | GitHubIssue | GitHubPullRequest | GitHubWorkflowRun)[]>([]);
  const [githubError, setGithubError] = useState<Failure | null>(null);
  const [githubLoading, setGithubLoading] = useState(false);
  const [startDate, setStartDate] = useState(isoDate(0));
  const [endDate, setEndDate] = useState(isoDate(7));
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [calendarError, setCalendarError] = useState<Failure | null>(null);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [notes, setNotes] = useState<Note[]>([]);
  const [notesLoading, setNotesLoading] = useState(true);
  const [notesError, setNotesError] = useState<Failure | null>(null);
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Note | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    void api.listGithubRepos().then((result) => {
      setRepoLoading(false);
      describeError(result, setRepoError);
      if (result.ok) {
        setRepos(result.data);
        if (result.data.length && !result.data.some((item) => item.full_name === repoDefault)) setRepo(result.data[0].full_name);
      }
    });
  }, []);

  useEffect(() => {
    if (tab !== 'github') return;
    if (githubView === 'repos') {
      setGithubLoading(repoLoading);
      setGithubError(repoError);
      setGithubData(repos);
      return;
    }
    setGithubLoading(true);
    setGithubError(null);
    const request = githubView === 'issues' ? api.listGithubIssues(repo)
      : githubView === 'pulls' ? api.listGithubPulls(repo)
        : api.listGithubRuns(repo);
    void request.then((result) => {
      setGithubLoading(false);
      if (!result.ok) setGithubError(result);
      else { setGithubError(null); setGithubData(result.data); }
    });
  }, [tab, githubView, repo, repos, repoError, repoLoading]);

  useEffect(() => {
    if (tab !== 'calendar') return;
    setCalendarLoading(true);
    setCalendarError(null);
    const start = new Date(`${startDate}T00:00:00+05:30`).toISOString();
    const end = new Date(`${endDate}T23:59:59+05:30`).toISOString();
    void api.listCalendarEvents(start, end, 'Asia/Kolkata').then((result) => {
      setCalendarLoading(false);
      describeError(result, setCalendarError);
      if (result.ok) setEvents(result.data);
    });
  }, [tab, startDate, endDate]);

  useEffect(() => {
    if (tab !== 'notes') return;
    setNotesLoading(true);
    void api.listNotes().then((result) => {
      setNotesLoading(false);
      describeError(result, setNotesError);
      if (result.ok) {
        setNotes(result.data);
        setSelectedNoteId((current) => result.data.some((note) => note.id === current) ? current : result.data[0]?.id ?? null);
      }
    });
  }, [tab]);

  const selectedNote = useMemo(() => notes.find((note) => note.id === selectedNoteId) ?? null, [notes, selectedNoteId]);
  useEffect(() => {
    setTitle(selectedNote?.title ?? '');
    setContent(selectedNote?.content ?? '');
  }, [selectedNote]);

  function newNote() {
    setSelectedNoteId(null);
    setTitle('');
    setContent('');
  }

  async function saveNote() {
    if (saving || !title.trim()) return;
    setSaving(true);
    setNotesError(null);
    const result = selectedNote
      ? await api.updateNote(selectedNote.id, title.trim(), content)
      : await api.createNote(title.trim(), content);
    setSaving(false);
    if (!result.ok) { setNotesError(result); toast('bad', `Couldn't save note. ${result.message}`); return; }
    setNotes((current) => selectedNote
      ? current.map((note) => note.id === result.data.id ? result.data : note)
      : [result.data, ...current]);
    setSelectedNoteId(result.data.id);
    toast('ok', selectedNote ? 'Note updated.' : 'Note created.');
  }

  async function deleteNote() {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    const result = await api.deleteNote(deleteTarget.id);
    setDeleting(false);
    if (!result.ok) { setNotesError(result); toast('bad', `Couldn't delete note. ${result.message}`); return; }
    setNotes((current) => current.filter((note) => note.id !== deleteTarget.id));
    setSelectedNoteId((current) => current === deleteTarget.id ? null : current);
    setDeleteTarget(null);
    toast('ok', 'Note deleted.');
  }

  function retryGithub() {
    setGithubLoading(true);
    setGithubError(null);
    if (githubView === 'repos') {
      void api.listGithubRepos().then((result) => {
        setGithubLoading(false);
        if (!result.ok) { setGithubError(result); return; }
        setRepos(result.data);
        setGithubData(result.data);
      });
      return;
    }
    const request = githubView === 'issues' ? api.listGithubIssues(repo)
      : githubView === 'pulls' ? api.listGithubPulls(repo)
        : api.listGithubRuns(repo);
    void request.then((result) => {
      setGithubLoading(false);
      if (!result.ok) setGithubError(result);
      else setGithubData(result.data);
    });
  }

  return (
    <div className="page integrations-page">
      <PageHeader title="Connectors & data" sub="Read from connected providers. Manage Cortexstone Notes here." />
      <div className="connector-studio-cards">
        <article className="connector-studio-card"><header><strong><Github size={14} /> GitHub</strong><span className="readonly">READ ONLY</span></header><p>Repositories, issues, pull requests, workflow runs</p><footer><span className={repoError ? 'readonly' : 'connected'}>{repoLoading ? 'CHECKING' : repoError ? 'UNAVAILABLE' : `${repos.length} REPOSITORIES`}</span><button className="btn" onClick={() => { setTab('github'); setGithubView('repos'); }}>Inspect</button></footer></article>
        <article className="connector-studio-card"><header><strong><CalendarDays size={14} /> Google Calendar</strong><span className="readonly">READ ONLY</span></header><p>Events queried in Asia/Kolkata</p><footer><span className={calendarError ? 'readonly' : 'connected'}>{calendarLoading ? 'CHECKING' : calendarError ? 'UNAVAILABLE' : `${events.length} EVENTS`}</span><button className="btn" onClick={() => setTab('calendar')}>Inspect</button></footer></article>
        <article className="connector-studio-card"><header><strong><NotebookPen size={14} /> Cortexstone Notes</strong><span className="connected">BUILT-IN CRUD</span></header><p>Create, edit, and delete owner-scoped notes</p><footer><span className={notesError ? 'readonly' : 'connected'}>{notesLoading ? 'CHECKING' : notesError ? 'UNAVAILABLE' : `${notes.length} NOTES`}</span><button className="btn" onClick={() => setTab('notes')}>Open studio</button></footer></article>
      </div>
      <p className="integration-note">Provider connect and disconnect controls are not exposed by this API. GitHub and Calendar remain read-only; no OAuth behavior is simulated here.</p>
      <nav className="connector-tabs" aria-label="Connector views">
        {connectorTabs.map(({ id, label, icon: Icon }) => <button key={id} className={`connector-tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)} aria-current={tab === id ? 'page' : undefined}><Icon size={16} />{label}</button>)}
      </nav>

      {tab === 'github' && (
        <section className="panel bento-card connector-view" aria-labelledby="github-view-title">
          <header className="bento-heading">
            <div><span className="eyebrow">PROVIDER · READ ONLY</span><h2 id="github-view-title">GitHub data explorer</h2></div>
            <Badge>Read-only</Badge>
          </header>
          {repoLoading ? <Loading what="repositories" /> : repoError ? <LoadError error={repoError} onRetry={() => { setRepoLoading(true); void api.listGithubRepos().then((result) => { setRepoLoading(false); describeError(result, setRepoError); if (result.ok) setRepos(result.data); }); }} /> : (
            <>
              <div className="explorer-toolbar">
                <label htmlFor="repo-select">Repository</label>
                <select id="repo-select" value={repo} onChange={(event) => setRepo(event.target.value)}>
                  {!repos.some((item) => item.full_name === repo) && <option value={repo}>{repo}</option>}
                  {repos.map((item) => <option key={item.full_name} value={item.full_name}>{item.full_name}</option>)}
                </select>
                <span className="muted">{repos.length} repositories</span>
              </div>
              <div className="inner-tabs" role="tablist" aria-label="GitHub repository data">
                {githubViews.map(({ id, label }) => <button role="tab" aria-selected={githubView === id} key={id} className={githubView === id ? 'active' : ''} onClick={() => setGithubView(id)}>{label}</button>)}
              </div>
              {githubLoading ? <Loading what={githubView} /> : githubError ? <LoadError error={githubError} onRetry={retryGithub} /> : githubData.length === 0 ? <Empty title={`No ${githubView} found`}>No data is available for {repo}.</Empty> : (
                <ul className="explorer-list">{githubData.map((item, index) => {
                  const repository = 'full_name' in item;
                  const run = 'conclusion' in item && 'created_at' in item ? item : null;
                  const key = repository ? item.full_name : run?.id ?? ('number' in item ? item.number : index);
                  return <li key={key}>
                    <span>{repository ? <>{item.full_name}<small className="muted"> · {item.private ? 'Private' : 'Public'}</small></> : run ? run.name : <>{'number' in item ? `#${item.number} ` : ''}{'title' in item ? item.title : ''} · {'state' in item ? item.state : ''}</>}</span>
                    {!repository && 'draft' in item && item.draft && <Badge>Draft</Badge>}
                    {run && <Badge tone={run.conclusion === 'success' ? 'ok' : run.conclusion === 'failure' ? 'bad' : 'neutral'}>{run.conclusion ?? run.status}</Badge>}
                    <span className="muted mono">{run?.created_at ? new Date(run.created_at).toLocaleString() : ''}</span>
                  </li>;
                })}</ul>
              )}
            </>
          )}
          <p className="integration-note">This connector exposes repository, issue, pull-request, and workflow-run reads only. No GitHub writes are available.</p>
        </section>
      )}

      {tab === 'calendar' && (
        <section className="panel bento-card connector-view" aria-labelledby="calendar-view-title">
          <header className="bento-heading"><div><span className="eyebrow">PROVIDER · READ ONLY</span><h2 id="calendar-view-title">Google Calendar events</h2></div><Badge>Read-only</Badge></header>
          <div className="explorer-toolbar date-toolbar">
            <div className="field"><label htmlFor="calendar-start">Start</label><input id="calendar-start" type="date" value={startDate} onChange={(event) => { const value = event.target.value; setStartDate(value); if (endDate < value) setEndDate(value); }} /></div>
            <div className="field"><label htmlFor="calendar-end">End</label><input id="calendar-end" type="date" value={endDate} min={startDate} onChange={(event) => setEndDate(event.target.value)} /></div>
            <span className="timezone-label">TIMEZONE <code>Asia/Kolkata</code></span>
          </div>
          {calendarLoading ? <Loading what="calendar events" /> : calendarError ? <LoadError error={calendarError} onRetry={() => { setCalendarLoading(true); const first = new Date(`${startDate}T00:00:00+05:30`).toISOString(); const last = new Date(`${endDate}T23:59:59+05:30`).toISOString(); void api.listCalendarEvents(first, last, 'Asia/Kolkata').then((result) => { setCalendarLoading(false); describeError(result, setCalendarError); if (result.ok) setEvents(result.data); }); }} /> : events.length === 0 ? <Empty title="No events in this range">Calendar returned no events for the selected period.</Empty> : (
            <ul className="explorer-list calendar-list">{events.map((event) => {
              const timezone = event.timezone || 'Asia/Kolkata';
              return <li key={event.id}><div><strong>{event.summary}</strong><span className="muted">{timezone}</span></div><span className="mono">{new Date(event.start).toLocaleString(undefined, { timeZone: timezone })} – {new Date(event.end).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZone: timezone })}</span></li>;
            })}</ul>
          )}
          <p className="integration-note">Event query uses <code>start</code>, <code>end</code>, and <code>timezone=Asia/Kolkata</code>. Calendar is read-only.</p>
        </section>
      )}

      {tab === 'notes' && (
        <section className="panel bento-card notes-view" aria-label="Cortexstone Notes manager">
          <header className="bento-heading"><div><span className="eyebrow">BUILT-IN · CREATE / READ / UPDATE / DELETE</span><h2>Cortexstone Notes</h2></div><button className="btn" onClick={newNote}><FilePlus2 size={15} />New note</button></header>
          {notesError && <div className="notes-error"><LoadError error={notesError} onRetry={() => { setNotesLoading(true); void api.listNotes().then((result) => { setNotesLoading(false); describeError(result, setNotesError); if (result.ok) { setNotes(result.data); setSelectedNoteId((current) => result.data.some((note) => note.id === current) ? current : result.data[0]?.id ?? null); } }); }} /></div>}
          <div className="notes-split">
            <aside className="notes-list" aria-label="Notes">
              {notesLoading ? <Loading what="notes" /> : notes.length ? notes.map((note) => (
                <button key={note.id} className={`note-list-item ${selectedNoteId === note.id ? 'selected' : ''}`} onClick={() => setSelectedNoteId(note.id)}>
                  <strong>{note.title}</strong><span>{note.content || 'Empty note'}</span><time>{new Date(note.updated_at).toLocaleDateString()}</time>
                </button>
              )) : <Empty title="No notes yet">Create your first note.</Empty>}
            </aside>
            <div className="note-editor">
              {notesLoading ? <Loading what="note editor" /> : (
                <>
                  <div className="note-editor-top"><span className="eyebrow">{selectedNote ? `NOTE · ${selectedNote.id}` : 'NEW NOTE'}</span>
                    {selectedNote && <button className="btn danger icon" aria-label="Delete selected note" onClick={() => setDeleteTarget(selectedNote)}><Trash2 size={15} /></button>}
                  </div>
                  <label className="sr" htmlFor="note-title">Note title</label><input id="note-title" className="note-title-input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Untitled note" maxLength={200} />
                  <label className="sr" htmlFor="note-content">Note content</label><textarea id="note-content" className="note-content-input" value={content} onChange={(event) => setContent(event.target.value)} placeholder="Write a note…" rows={12} />
                  <footer className="note-editor-footer"><span className="muted">{selectedNote ? `Updated ${new Date(selectedNote.updated_at).toLocaleString()}` : 'Notes are scoped to your account.'}</span><button className="btn primary" onClick={() => void saveNote()} disabled={saving || !title.trim()}><Save size={15} />{saving ? 'Saving…' : selectedNote ? 'Save changes' : 'Create note'}</button></footer>
                </>
              )}
            </div>
          </div>
          <div className="integration-note">GitHub and Calendar remain read-only. Note writes are scoped to the authenticated principal.</div>
        </section>
      )}
      <ConfirmDialog open={deleteTarget !== null} title="Delete this note?" confirmLabel="Delete note" busy={deleting} onConfirm={() => void deleteNote()} onCancel={() => setDeleteTarget(null)}>
        <p>This permanently deletes <strong>{deleteTarget?.title}</strong> from your notes.</p>
      </ConfirmDialog>
    </div>
  );
}
