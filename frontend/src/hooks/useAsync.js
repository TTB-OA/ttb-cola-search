import { useEffect, useState } from 'react';

// Runs an async function whenever `deps` change, exposing {data, loading, error}.
// Aborts stale requests via an AbortController passed to the callback.
export function useAsync(fn, deps, { skip = false } = {}) {
  const [state, setState] = useState({ data: null, loading: !skip, error: null });

  useEffect(() => {
    if (skip) {
      setState({ data: null, loading: false, error: null });
      return undefined;
    }
    let alive = true;
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.resolve(fn(controller.signal)).then(
      (data) => {
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
