import { useMemo, useState } from 'react';
import { api } from '../app-context';
import type { JobRecord, JobStatus } from '../api/types';
import { useLoad } from '../hooks';
import { Modal } from '../dialog';
import { LoadError, Loading } from '../states';
import { Badge, Empty, PageHeader, fmtTime, type Tone } from '../ui';

const STATUS: Record<JobStatus, [string, Tone]> = {
  queued: ['Queued', 'neutral'], running: ['Running', 'info'], retry_wait: ['Retrying', 'warn'], awaiting_approval: ['Waiting for approval', 'warn'],
  succeeded: ['Succeeded', 'ok'], failed: ['Failed', 'bad'], cancelled: ['Cancelled', 'neutral'],
};

export default function Jobs() {
  const { data, error, loading, reload } = useLoad(api.listJobs);
  const [status, setStatus] = useState<'all' | JobStatus>('all');
  const [open, setOpen] = useState<JobRecord | null>(null);
  const rows = useMemo(() => (data ?? []).filter((j) => status === 'all' || j.status === status), [data, status]);
  return (
    <div className="page">
      <PageHeader title="Jobs & workflows" sub="Background work, its outcome, and how many attempts it took." />
      <section className="panel" aria-label="Jobs">
        <div className="toolbar">
          <label htmlFor="js" className="sr">Status</label>
          <select id="js" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            <option value="all">All statuses</option>{(Object.keys(STATUS) as JobStatus[]).map((s) => <option key={s} value={s}>{STATUS[s][0]}</option>)}
          </select>
          <span className="muted" aria-live="polite">{data ? `${rows.length} of ${data.length}` : ''}</span>
        </div>
        {loading ? <Loading what="jobs" /> : error ? <LoadError error={error} onRetry={() => void reload()} /> : rows.length === 0 ? (
          <Empty title="No jobs with this status" action={<button className="btn" onClick={() => setStatus('all')}>Show all jobs</button>}>Pick another status to see more.</Empty>
        ) : (
          <div className="scroll"><table>
            <thead><tr><th>Job</th><th>Status</th><th>Started</th><th>Duration</th><th>Attempts</th><th><span className="sr">Details</span></th></tr></thead>
            <tbody>{rows.map((j) => (
              <tr key={j.id}><td>{j.name}</td><td><Badge tone={STATUS[j.status][1]}>{STATUS[j.status][0]}</Badge></td><td className="muted">{fmtTime(j.startedAt)}</td>
                <td className="mono">{j.durationS === null ? '–' : `${j.durationS}s`}</td><td className="mono">{j.attempts}</td>
                <td><button className="btn" onClick={() => setOpen(j)} aria-label={`Details for ${j.name}`}>Details</button></td></tr>))}</tbody>
          </table></div>
        )}
      </section>
      <Modal open={open !== null} title={open?.name ?? ''} onClose={() => setOpen(null)}>
        {open && <><p><Badge tone={STATUS[open.status][1]}>{STATUS[open.status][0]}</Badge></p><p style={{ marginTop: 12 }}>{open.outcome}</p>
          <p className="muted" style={{ marginTop: 12 }}>Started {fmtTime(open.startedAt)} · {open.attempts} attempt{open.attempts === 1 ? '' : 's'}</p></>}
      </Modal>
    </div>
  );
}
