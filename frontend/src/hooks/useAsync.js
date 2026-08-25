import { useEffect, useState } from 'react';

// Short-lived response cache, opt in per call with `cacheKey`. Back/forward
// navigation then re-renders from memory instead of refetching.
const CACHE_TTL_MS = 5 * 60 * 1000;
const CACHE_MAX = 50;
const cache = new Map();

function cacheGet(key) {
  if (!key) return undefined;
  const hit = cache.get(key);
  if (!hit) return undefined;
  if (Date.now() - hit.at > CACHE_TTL_MS) {
    cache.delete(key);
    return undefined;
  }
  cache.delete(key);
  cache.set(key, hit); // re-insert: Map iterates in insertion order, so this is the LRU tail
  return hit.data;
}

function cachePut(key, data) {
  if (!key) return;
  cache.set(key, { data, at: Date.now() });
  while (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value);
}

// Runs an async function whenever `deps` change, exposing {data, loading, error}.
// Aborts stale requests via an AbortController passed to the callback.
export function useAsync(fn, deps, { skip = false, cacheKey = null } = {}) {
  const [state, setState] = useState(() => {
    const hit = skip ? undefined : cacheGet(cacheKey);
    if (hit !== undefined) return { data: hit, loading: false, error: null };
    return { data: null, loading: !skip, error: null };
  });

  useEffect(() => {
    if (skip) {
      setState({ data: null, loading: false, error: null });
      return undefined;
    }
    const hit = cacheGet(cacheKey);
    if (hit !== undefined) {
      setState({ data: hit, loading: false, error: null });
      return undefined;
    }
    let alive = true;
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.resolve(fn(controller.signal)).then(
      (data) => {
        cachePut(cacheKey, data);
        if (alive) setState({ data, loading: false, error: null });
      },
      (error) => {
        if (alive && error.name !== 'AbortError') {
          setState({ data: null, loading: false, error });
        }
      }
    );
    return () => {
      alive = false;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
