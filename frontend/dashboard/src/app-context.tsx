import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { createApi } from './api/client';
import { config } from './config';
import type { DataMode, DemoScenario, HealthSnapshot } from './api/types';

export const API_BASE = config.apiBase;
export let api = createApi(config.mode, config.apiBase);

interface H {
  snap: HealthSnapshot | null;
  loading: boolean;
  mode: DataMode;
  scenario: DemoScenario;
  refresh: () => void;
  setMode: (mode: DataMode) => void;
  setScenario: (scenario: DemoScenario) => void;
}
const Ctx = createContext<H>({
  snap: null, loading: false, mode: config.mode, scenario: 'normal',
  refresh: () => {}, setMode: () => {}, setScenario: () => {},
});
export const useHealth = () => useContext(Ctx);

export function overall(s: HealthSnapshot | null): 'checking' | 'ok' | 'degraded' | 'unreachable' {
  if (!s) return 'checking';
  if (s.health.state === 'unreachable') return 'unreachable';
  return [s.health, s.ready].every((p) => p.state === 'ok') ? 'ok' : 'degraded';
}

export function HealthProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<DataMode>(config.mode);
  const [scenario, setScenario] = useState<DemoScenario>('normal');
  const [snap, setSnap] = useState<HealthSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    api = createApi(mode, config.apiBase, mode === 'mock' ? scenario : 'normal');
    setSnap(null);
  }, [mode, scenario]);
  const refresh = useCallback(async () => {
    setLoading(true);
    const r = await api.health();
    setLoading(false);
    if (r.ok) setSnap(r.data);
  }, [mode, scenario]);
  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), mode === 'live' ? 30000 : 5000);
    return () => clearInterval(id);
  }, [refresh, mode]);
  const value = useMemo(() => ({
    snap, loading, mode, scenario, refresh: () => void refresh(), setMode,
    setScenario: (next: DemoScenario) => { if (mode === 'mock') setScenario(next); },
  }), [snap, loading, mode, scenario, refresh]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
