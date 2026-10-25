import { useEffect, useMemo, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Brain, FileCheck2, LayoutDashboard, Menu, MessageSquare, PanelLeftClose, PanelLeftOpen, Plug, Search, Settings as Cog, ShieldAlert, Workflow } from 'lucide-react';
import { API_BASE, HealthProvider, api, overall, useHealth } from './app-context';
import type { DataMode, DemoScenario, Feature } from './api/types';
import { Badge, Banner, Empty } from './ui';
import { Modal } from './dialog';
import Overview from './pages/Overview';
import Chat from './pages/Chat';
import Actions from './pages/Actions';
import Memory from './pages/Memory';
import Jobs from './pages/Jobs';
import Guardian from './pages/Guardian';
import Integrations from './pages/Integrations';
import { ToastProvider } from './toast';
import { config } from './config';

const NAV: { id: string; label: string; icon: typeof Cog; feature?: Feature }[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'chat', label: 'Chat', icon: MessageSquare, feature: 'chat' },
  { id: 'memory', label: 'Memory', icon: Brain, feature: 'memory' },
  { id: 'jobs', label: 'Jobs & Workflows', icon: Workflow, feature: 'jobs' },
  { id: 'actions', label: 'Actions & Approvals', icon: FileCheck2, feature: 'actions' },
  { id: 'guardian', label: 'Guardian', icon: ShieldAlert, feature: 'guardian' },
  { id: 'integrations', label: 'Integrations', icon: Plug, feature: 'integrations' },
  { id: 'settings', label: 'Settings', icon: Cog },
];
const SCENARIOS: { id: DemoScenario; label: string }[] = [
  { id: 'normal', label: 'Normal' }, { id: 'loading', label: 'Loading' }, { id: 'empty', label: 'Empty' },
  { id: 'unauthenticated', label: '401 Auth' }, { id: 'forbidden', label: '403 Forbidden' },
  { id: 'reauth', label: 'Needs Reauth' }, { id: 'outage', label: '503 Outage' },
];

const useRoute = () => {
  const get = () => (location.hash.replace(/^#\//, '').split('?')[0] || 'overview');
  const [r, setR] = useState(get);
  useEffect(() => { const f = () => setR(get()); addEventListener('hashchange', f); return () => removeEventListener('hashchange', f); }, []);
  return r;
};

const UNAVAILABLE: Record<string, { feature: Feature; title: string; paths: string[] }> = {
  jobs: { feature: 'jobs', title: 'Jobs & Workflows', paths: ['GET /api/v1/jobs', 'GET /api/v1/jobs/{id}'] },
  guardian: { feature: 'guardian', title: 'Guardian', paths: ['GET /api/v1/findings'] },
};

function UnavailablePage({ title, paths }: { title: string; paths: string[] }) {
  return <div className="page"><h1>{title}</h1><section className="panel"><Empty title="No live endpoint is registered">This view is only available in the sandbox. The live backend has not registered these routes.</Empty><ul className="list">{paths.map((path) => <li key={path}><code>{path}</code><Badge>Unavailable</Badge></li>)}</ul></section></div>;
}

function SettingsPage() {
  const { snap, mode, scenario, setMode } = useHealth();
  const rows: [string, React.ReactNode][] = [
    ['Data mode', mode === 'live' ? 'Live backend' : 'Simulated sandbox'],
    ['API base URL', API_BASE ? <code>{API_BASE}</code> : <span>Same origin (Vite proxy)</span>],
    ['Connection', mode === 'mock' ? 'Sandbox' : overall(snap)],
    ['Signed in as', snap?.principal?.authenticated ? `${snap.principal.display_name} · ${snap.principal.id}` : 'No authenticated principal returned by /api/v1/me.'],
    ['Scenario', mode === 'mock' ? scenario : 'Scenarios are available in sandbox mode only.'],
  ];
  return <div className="page"><div className="head"><div><h1>Settings</h1><p>Connection and account status for this dashboard.</p></div></div>
    <section className="panel"><div className="scroll"><table><tbody>{rows.map(([key, value]) => <tr key={key}><th scope="row" style={{ width: 200 }}>{key}</th><td>{value}</td></tr>)}</tbody></table></div></section>
    <Banner title="Identity is server-side">The API derives identity from verified credentials. This dashboard never sends a user id or stores provider credentials.</Banner>
    <button className="btn" onClick={() => setMode(mode === 'mock' ? 'live' : 'mock')}>Switch to {mode === 'mock' ? 'Live API' : 'Simulated Sandbox'}</button>
  </div>;
}

function Page({ route }: { route: string }) {
  if (route === 'integrations') return <Integrations />;
  const u = UNAVAILABLE[route];
  if (u) return api.support[u.feature] === 'unavailable' ? <UnavailablePage title={u.title} paths={u.paths} /> : route === 'jobs' ? <Jobs /> : <Guardian />;
  switch (route) {
    case 'chat': return <Chat />;
    case 'memory': return <Memory />;
    case 'actions': return <Actions />;
    case 'settings': return <SettingsPage />;
    default: return <Overview />;
  }
}

function Shell() {
  const route = useRoute();
  const { snap, mode, scenario, setMode, setScenario } = useHealth();
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('cs.collapsed') === '1'; } catch { return false; } });
  const [open, setOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteQuery, setPaletteQuery] = useState('');
  const [paletteIndex, setPaletteIndex] = useState(0);
  const [latencyHistory, setLatencyHistory] = useState<{ health: number; ready: number }[]>([]);
  useEffect(() => { setOpen(false); }, [route]);
  useEffect(() => {
    if (!snap?.health.ms || !snap.ready.ms) return;
    setLatencyHistory((history) => [...history.slice(-17), { health: snap.health.ms!, ready: snap.ready.ms! }]);
  }, [snap]);
  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen((value) => !value);
      }
    };
    addEventListener('keydown', onKeyDown);
    return () => removeEventListener('keydown', onKeyDown);
  }, []);
  useEffect(() => { if (!paletteOpen) setPaletteQuery(''); }, [paletteOpen]);
  const toggle = () => setCollapsed((c) => { try { localStorage.setItem('cs.collapsed', c ? '0' : '1'); } catch { /* ignore */ } return !c; });
  const matches = useMemo(() => NAV.filter(({ label, id }) => `${label} ${id}`.toLowerCase().includes(paletteQuery.trim().toLowerCase())), [paletteQuery]);
  useEffect(() => { setPaletteIndex(0); }, [paletteQuery]);
  const navigateTo = (id: string) => { location.hash = `#/${id}`; setPaletteOpen(false); };
  const onPaletteKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' && matches.length) { event.preventDefault(); setPaletteIndex((index) => (index + 1) % matches.length); }
    if (event.key === 'ArrowUp' && matches.length) { event.preventDefault(); setPaletteIndex((index) => (index + matches.length - 1) % matches.length); }
    if (event.key === 'Enter' && matches[paletteIndex]) { event.preventDefault(); navigateTo(matches[paletteIndex].id); }
  };
  const health = snap?.health;
  const ready = snap?.ready;
  const activeRoute = NAV.find((item) => item.id === route);
  const chartPoints = (key: 'health' | 'ready') => latencyHistory.map((entry, index) => {
    const maximum = Math.max(20, ...latencyHistory.map((value) => value[key]));
    const x = latencyHistory.length < 2 ? 0 : index * 100 / (latencyHistory.length - 1);
    const y = 22 - entry[key] / maximum * 18;
    return `${x},${y}`;
  }).join(' ');

  return (
    <div className={`app${collapsed ? ' collapsed' : ''}${open ? ' open' : ''}`}>
      <header className="top">
        <button className="btn icon only-m" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu size={18} /></button>
        <div className="brand only-m"><span className="mark" aria-hidden><i /><i /><i /></span>Cortexstone</div>
        <div className="top-breadcrumb hide-m"><span>WORKSPACE</span><b>/</b><strong>{activeRoute?.label ?? 'Overview'}</strong></div>
        <div className="top-telemetry hide-m" aria-label="API latency">
          <svg viewBox="0 0 100 24" role="img" aria-label="Health and readiness latency waveform">
            <polyline points={chartPoints('health')} className="wave-health" />
            <polyline points={chartPoints('ready')} className="wave-ready" />
          </svg>
          <span><code>{health?.ms ?? '—'}ms</code><small>HEALTH</small></span>
          <span><code>{ready?.ms ?? '—'}ms</code><small>READY</small></span>
        </div>
        <div className="mode-switch" role="group" aria-label="API mode">
          <button className={mode === 'live' ? 'selected live' : ''} onClick={() => setMode('live')} aria-pressed={mode === 'live'}>● LIVE API</button>
          <button className={mode === 'mock' ? 'selected sandbox' : ''} onClick={() => setMode('mock')} aria-pressed={mode === 'mock'}>◈ SIMULATED SANDBOX</button>
        </div>
        <label className="scenario-switch hide-m"><span>SCENARIO</span><select aria-label="Sandbox scenario" value={scenario} disabled={mode === 'live'} onChange={(event) => setScenario(event.target.value as DemoScenario)}>{SCENARIOS.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
        <button className="command-trigger hide-m" onClick={() => setPaletteOpen(true)} aria-keyshortcuts="Control+K Meta+K"><Search size={15} /><span>Jump to…</span><kbd>⌘ K / Ctrl K</kbd></button>
        <span className={`telemetry-pulse top-pulse ${health?.state ?? 'checking'}`} aria-label={`Health ${health?.state ?? 'checking'}`} />
      </header>
      <div className="scrim" onClick={() => setOpen(false)} />
      <nav className="side" aria-label="Primary">
        <div className="brand"><span className="mark" aria-hidden><i /><i /><i /></span><b>Cortexstone</b></div>
        {NAV.map(({ id, label, icon: Icon, feature }) => {
          const s = feature ? api.support[feature] : undefined;
          const status = s === 'live' ? 'live data' : s === 'simulated' ? 'simulated data' : s ? 'not available yet' : '';
          return (
            <a key={id} href={`#/${id}`} className="nav" aria-current={route === id ? 'page' : undefined} title={label} aria-label={status ? `${label}, ${status}` : label}>
              <Icon size={18} aria-hidden /><span className="lbl">{label}</span>
            </a>
          );
        })}
        <span className="spacer" />
        <button className="btn hide-m" onClick={toggle} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
          {collapsed ? <PanelLeftOpen size={16} /> : <><PanelLeftClose size={16} /><span className="lbl">Collapse</span></>}
        </button>
      </nav>
      <main className="main" id="main"><Page key={`${route}-${mode}-${scenario}`} route={route} /></main>
      <Modal open={paletteOpen} title="Jump to" onClose={() => setPaletteOpen(false)}>
        <div className="palette-search"><Search size={16} /><input autoFocus value={paletteQuery} onChange={(event) => setPaletteQuery(event.target.value)} onKeyDown={onPaletteKeyDown} placeholder="Search pages…" aria-label="Search pages" /></div>
        <nav className="palette-results" aria-label="Page shortcuts">
          {matches.map(({ id, label, icon: Icon }, index) => (
            <a key={id} href={`#/${id}`} className={`palette-result ${paletteIndex === index ? 'selected' : ''}`} onClick={() => setPaletteOpen(false)} aria-current={route === id ? 'page' : undefined}>
              <Icon size={16} /><span>{label}</span><kbd>↵</kbd>
            </a>
          ))}
          {matches.length === 0 && <p className="muted palette-empty">No matching pages.</p>}
        </nav>
      </Modal>
    </div>
  );
}

export default function App() {
  if (config.error) return <main className="cfg"><h1>Configuration error</h1><p className="muted" style={{ marginTop: 8 }}>{config.error}</p><p className="muted" style={{ marginTop: 8 }}>Fix the value in <code>.env</code> and restart. Nothing was requested.</p></main>;
  return <ToastProvider><HealthProvider><Shell /></HealthProvider></ToastProvider>;
}
