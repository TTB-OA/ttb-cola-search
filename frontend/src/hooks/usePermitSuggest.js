import { useEffect, useState } from 'react';
import { api } from '../lib/api.js';

const DEBOUNCE_MS = 250;
const MIN_TERM = 2;

/**
 * Debounced permit typeahead. Returns `{ options, loading }` shaped for
 * `Combobox`, with the raw suggestion kept on `permit` so a pick can fill the
 * rest of the permit fields.
 */
export function usePermitSuggest(term, toOption) {
  const [state, setState] = useState({ options: [], loading: false });

  useEffect(() => {
    const q = (term || '').trim();
    if (q.length < MIN_TERM) {
      setState({ options: [], loading: false });
      return undefined;
    }
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true }));
    const timer = setTimeout(() => {
      api
        .suggestPermits({ q }, controller.signal)
        .then((rows) =>
          setState({
            options: (rows || []).map((p) => ({ ...toOption(p), key: p.permitId, permit: p })),
            loading: false,
          })
        )
        .catch(() => {
          if (!controller.signal.aborted) setState({ options: [], loading: false });
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // toOption is defined inline by callers; the term is what drives the fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [term]);

  return state;
}
