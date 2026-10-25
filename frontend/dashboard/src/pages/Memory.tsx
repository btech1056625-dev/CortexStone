import { useMemo, useState, type FormEvent } from 'react';
import { api } from '../app-context';
import type { MemoryKind, MemoryRecord } from '../api/types';
import { useLoad } from '../hooks';
import { ConfirmDialog } from '../dialog';
import { useToast } from '../toast';
import { LoadError, Loading } from '../states';
import { Badge, Empty, PageHeader, fmtTime } from '../ui';

export default function Memory() {
  const { data, error, loading, reload, setData } = useLoad(api.listMemories);
  const toast = useToast();
  const [q, setQ] = useState(''); const [prov, setProv] = useState<'all' | 'stated' | 'inferred'>('all'); const [kind, setKind] = useState<'all' | MemoryKind>('all');
  const [content, setContent] = useState(''); const [newKind, setNewKind] = useState<MemoryKind>('fact'); const [creating, setCreating] = useState(false);
  const [target, setTarget] = useState<MemoryRecord | null>(null); const [busy, setBusy] = useState(false);
  const rows = useMemo(() => (data ?? []).filter((m) =>
    (prov === 'all' || (prov === 'inferred') === m.inferred) && (kind === 'all' || m.kind === kind) && m.content.toLowerCase().includes(q.trim().toLowerCase())), [data, q, prov, kind]);
  const inferredCount = rows.filter((memory) => memory.inferred).length;
  const userCount = rows.length - inferredCount;

  async function create(event: FormEvent) {
    event.preventDefault();
    if (creating || !content.trim()) return;
    setCreating(true);
    const result = await api.createMemory({ content: content.trim(), kind: newKind });
    setCreating(false);
    if (!result.ok) { toast('bad', `Couldn't add memory. ${result.message}`); return; }
    setData([result.data, ...(data ?? [])]);
    setContent('');
    toast('ok', 'Memory added.');
  }

  async function forget() {
    if (!target || busy || !data) return;
    setBusy(true);
    const r = await api.forgetMemory(target.id);
    setBusy(false);
    if (!r.ok) { toast('bad', `Couldn't forget this memory. ${r.message}`); return; }
    setData(data.filter((m) => m.id !== target.id));
    setTarget(null);
    toast('ok', 'Memory forgotten.');
  }

  return (
    <div className="page">
      <PageHeader title="Memory" sub="What Cortexstone remembers, where it came from, and how sure it is." />
      <section className="panel" aria-label="Memories">
        <form className="memory-create-bar" onSubmit={(event) => void create(event)}>
          <label className="sr" htmlFor="memory-content">Memory content</label>
          <input id="memory-content" value={content} onChange={(event) => setContent(event.target.value)} maxLength={2000} placeholder="Add a user-stated memory…" />
          <label className="sr" htmlFor="memory-kind">Memory type</label>
          <select id="memory-kind" value={newKind} onChange={(event) => setNewKind(event.target.value as MemoryKind)}>
            <option value="fact">Fact</option><option value="preference">Preference</option><option value="context">Context</option>
          </select>
          <button className="btn primary" type="submit" disabled={creating || !content.trim()}>{creating ? 'Adding…' : 'Add memory'}</button>
        </form>
        <div className="toolbar">
          <div className="search"><label htmlFor="mq" className="sr">Search memories</label><input id="mq" type="search" placeholder="Search memories" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <label className="sr" htmlFor="mp">Provenance</label>
          <select id="mp" value={prov} onChange={(e) => setProv(e.target.value as typeof prov)}><option value="all">All provenance</option><option value="stated">Stated by you</option><option value="inferred">Inferred</option></select>
          <label className="sr" htmlFor="mk">Kind</label>
          <select id="mk" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}><option value="all">All types</option><option value="fact">Fact</option><option value="preference">Preference</option><option value="context">Context</option></select>
        </div>
        {!loading && !error && <div className="source-breakdown" aria-label={`Source provenance: ${userCount} user-stated, ${inferredCount} inferred`}>
          <div><span>Source provenance</span><span>{userCount} user-stated · {inferredCount} inferred</span></div>
          <div className="source-meter"><i className="user-segment" style={{ width: `${rows.length ? userCount / rows.length * 100 : 0}%` }} /><i className="inferred-segment" style={{ width: `${rows.length ? inferredCount / rows.length * 100 : 0}%` }} /></div>
        </div>}
        {loading ? <Loading what="memories" /> : error ? <LoadError error={error} onRetry={() => void reload()} /> : rows.length === 0 ? (
          (data ?? []).length === 0 ? <Empty title="Nothing remembered yet">Facts you share in chat will appear here with their source.</Empty>
            : <Empty title="No memories match" action={<button className="btn" onClick={() => { setQ(''); setProv('all'); setKind('all'); }}>Clear filters</button>}>Try a different search or clear the filters.</Empty>
        ) : (
          <div className="scroll"><table className="memory-table">
            <thead><tr><th>Memory</th><th>Provenance</th><th>Confidence</th><th>Added</th><th aria-label="Actions" /></tr></thead>
            <tbody>{rows.map((m) => (
              <tr key={m.id}>
                <td style={{ minWidth: 220 }}><div>{m.content}</div><div className="muted">{m.kind} · {m.source}</div></td>
                <td>{m.inferred ? <Badge tone="memory">Inferred</Badge> : <Badge tone="ok">Stated by you</Badge>}</td>
                <td><div className="memory-meter" role="img" aria-label={`Confidence ${Math.round(m.confidence * 100)} percent`}>{Array.from({ length: 10 }, (_, index) => <i className={index < Math.round(m.confidence * 10) ? 'filled' : ''} key={index} />)}</div><span className="mono">{m.confidence.toFixed(2)}</span></td>
                <td className="muted">{fmtTime(m.createdAt)}</td>
                <td><button className="btn danger" onClick={() => setTarget(m)} aria-label={`Forget memory: ${m.content}`}>Forget</button></td>
              </tr>))}</tbody>
          </table></div>
        )}
      </section>
      <ConfirmDialog open={target !== null} title="Forget this memory?" confirmLabel="Forget memory" busy={busy} onConfirm={() => void forget()} onCancel={() => setTarget(null)}>
        <p>{target?.content}</p><p className="muted" style={{ marginTop: 8 }}>Cortexstone will stop using it in answers. This can't be undone from the dashboard.</p>
      </ConfirmDialog>
    </div>
  );
}
