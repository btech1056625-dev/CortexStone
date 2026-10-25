import type { DataMode } from './api/types';

export interface Config { mode: DataMode; apiBase: string; error: string | null }
interface RawEnv { VITE_DATA_MODE?: string; VITE_API_BASE_URL?: string }

export const API_PATHS = {
  health: '/health',
  ready: '/ready',
  principal: '/api/v1/me',
  validateAction: '/api/v1/actions/validate',
  memories: '/api/v1/memories',
  githubRepos: '/api/v1/connectors/github/repos',
  calendarEvents: '/api/v1/connectors/calendar/events',
  notes: '/api/v1/notes',
} as const;

const LOCAL_HOSTS = ['localhost', '127.0.0.1', '[::1]'];
const invalid = (error: string): Config => ({ mode: 'mock', apiBase: '', error });

/** VITE_* values are public. Validate them; never treat them as secrets. */
export function parseConfig(env: RawEnv): Config {
  const mode = (env.VITE_DATA_MODE ?? 'mock').trim();
  if (mode !== 'mock' && mode !== 'live') return invalid(`VITE_DATA_MODE must be "mock" or "live" (got "${mode}").`);
  const base = (env.VITE_API_BASE_URL ?? '').trim();
  if (!base) return { mode, apiBase: '', error: null };
  let url: URL;
  try { url = new URL(base); } catch { return invalid('VITE_API_BASE_URL must be an absolute http(s) URL, or empty to use the dev proxy.'); }
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && LOCAL_HOSTS.includes(url.hostname))) return invalid('VITE_API_BASE_URL must use https. Plain http is allowed only for localhost.');
  if (url.username || url.password || url.search || url.hash) return invalid('VITE_API_BASE_URL must not contain credentials, a query string, or a fragment.');
  return { mode, apiBase: url.origin + url.pathname.replace(/\/$/, ''), error: null };
}

export const config = parseConfig({
  VITE_DATA_MODE: import.meta.env.VITE_DATA_MODE as string | undefined,
  VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL as string | undefined,
});
