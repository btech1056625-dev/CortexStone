import { RefreshCw } from 'lucide-react';
import type { Failure } from './api/types';
import { Banner } from './ui';

export const Loading = ({ what }: { what: string }) => <div className="body muted" role="status">Loading {what}…</div>;

export function LoadError({ error, onRetry }: { error: Failure; onRetry: () => void }) {
  const title = error.kind === 'unauthenticated' ? 'Sign-in required' : error.kind === 'forbidden' ? 'Not permitted' : error.kind === 'network' ? 'API unreachable' : 'Could not load';
  return (
    <div className="body"><Banner tone="bad" title={title}>
      <p>{error.message}</p>{error.requestId && <p>Request ID: <code>{error.requestId}</code></p>}
      <p><button className="btn" onClick={onRetry}><RefreshCw size={14} aria-hidden />Try again</button></p>
    </Banner></div>
  );
}
