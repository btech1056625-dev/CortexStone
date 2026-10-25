import { useCallback, useEffect, useState } from 'react';
import type { Failure, Result } from './api/types';

export function useLoad<T>(fetcher: () => Promise<Result<T>>) {
  const [state, setState] = useState<{ data: T | null; error: Failure | null; loading: boolean }>({ data: null, error: null, loading: true });
  const reload = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }));
    const r = await fetcher();
    setState(r.ok ? { data: r.data, error: null, loading: false } : { data: null, error: r, loading: false });
  }, [fetcher]);
  useEffect(() => { void reload(); }, [reload]);
  const setData = (data: T) => setState((s) => ({ ...s, data }));
  return { ...state, reload, setData };
}
