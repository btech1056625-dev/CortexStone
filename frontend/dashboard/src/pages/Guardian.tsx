import { useMemo, useState } from 'react';
import { api } from '../app-context';
import type { Finding, Severity } from '../api/types';
import { useLoad } from '../hooks';
import { Modal } from '../dialog';
import { LoadError, Loading } from '../states';
import { Badge, Empty, PageHeader, fmtTime, type Tone } from '../ui';

const SEV: Record<Severity, Tone> = { critical: 'bad', high: 'warn', medium: 'info', low: 'neutral' };

export default function Guardian() {
  const { data, error, loading, reload } = useLoad(api.listFindings);
  const [sev, setSev] = useState<'all' | Severity>('all');
  const [open, setOpen] = useState<Finding | null>(null);
  const rows = useMemo(() => (data ?? []).filter((f) => sev === 'all' || f.severity === sev), [data, sev]);
  return (
    <div className="page">
      <PageHeader title="Guardian" sub="Security findings, by severity and the resource they affect.">
        <button className="btn" disabled aria-describedby="scan-note">Run scan</button>
      </PageHeader>
      <p id="scan-note" className="muted" style={{ marginTop: -12 }}>Scanning isn't available: Guardian has no backend yet. These findings are demonstration data, not results from your code.</p>
      <section className="panel" aria-label="Findings">
        <div className="toolbar">
          <label htmlFor="sv" className="sr">Severity</label>
          <select id="sv" value={sev} onChange={(e) => setSev(e.target.value as typeof sev)}><option value="all">All severities</option>{(Object.keys(SEV) as Severity[]).map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}</select>
        </div>
        {loading ? <Loading what="findings" /> : error ? <LoadError error={error} onRetry={() => void reload()} /> : rows.length === 0 ? (
          <Empty title="No findings at this severity" action={<button className="btn" onClick={() => setSev('all')}>Show all</button>}>Nothing to show for this filter.</Empty>
        ) : (
          <div className="scroll"><table>
            <thead><tr><th>Severity</th><th>Finding</th><th>Affected resource</th><th>Status</th><th>Found</th><th><span className="sr">Details</span></th></tr></thead>
            <tbody>{rows.map((f) => (
              <tr key={f.id}><td><Badge tone={SEV[f.severity]}>{f.severity}</Badge></td><td>{f.title}</td><td><code>{f.resource}</code></td>
                <td>{f.status === 'open' ? <Badge tone="warn">Open</Badge> : <Badge tone="ok">Resolved</Badge>}</td><td className="muted">{fmtTime(f.foundAt)}</td>
                <td><button className="btn" onClick={() => setOpen(f)} aria-label={`Details for ${f.title}`}>Details</button></td></tr>))}</tbody>
          </table></div>
        )}
      </section>
      <Modal open={open !== null} title={open?.title ?? ''} onClose={() => setOpen(null)}>
        {open && <><p><Badge tone={SEV[open.severity]}>{open.severity}</Badge></p><p style={{ marginTop: 12 }}>{open.detail}</p><p style={{ marginTop: 12 }}><code>{open.resource}</code></p></>}
      </Modal>
    </div>
  );
}
