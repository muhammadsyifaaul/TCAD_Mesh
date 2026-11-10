/**
 * dashboard/src/hooks.js
 * Polling hooks — all data fetches use 2-second intervals.
 */
import { useState, useEffect, useCallback } from 'react';
import { api } from './api';

const POLL_MS = 2000;

function usePoll(fetcher, deps = []) {
  const [data,    setData]  = useState(null);
  const [error,   setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const run = useCallback(async () => {
    try {
      const result = await fetcher();
      setData(result);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    run();
    const id = setInterval(run, POLL_MS);
    return () => clearInterval(id);
  }, [run]);

  return { data, error, loading, refresh: run };
}

export const useStats      = () => usePoll(() => api.getStats());
export const useEvents     = (params) => usePoll(() => api.getEvents(params), [JSON.stringify(params)]);
export const useQuarantine = () => usePoll(() => api.getQuarantine());
export const useHoneytokens= () => usePoll(() => api.getHoneytokens());
export const useSimStatus  = () => usePoll(() => api.getSimStatus());
