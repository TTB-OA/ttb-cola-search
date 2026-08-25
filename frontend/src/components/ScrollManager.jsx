// BrowserRouter does not manage scroll, so a click from a scrolled result list
// used to land mid-page on the next route. New pages start at the top; back and
// forward return to where the user left off.
import { useEffect, useLayoutEffect, useRef } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

const positions = new Map();
const RESTORE_TIMEOUT_MS = 1200;

export default function ScrollManager() {
  const { key, pathname } = useLocation();
  const navType = useNavigationType();
  const keyRef = useRef(key);
  const pathRef = useRef(pathname);

  useEffect(() => {
    if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';
    const onScroll = () => positions.set(keyRef.current, window.scrollY);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useLayoutEffect(() => {
    keyRef.current = key;
    const pathChanged = pathRef.current !== pathname;
    pathRef.current = pathname;

    if (navType !== 'POP') {
      // Facet, sort and paging changes keep the same path and handle their own scrolling.
      if (pathChanged) window.scrollTo(0, 0);
      return undefined;
    }

    const y = positions.get(key) || 0;
    if (!y) {
      window.scrollTo(0, 0);
      return undefined;
    }

    // The restored page may still be fetching, so retry until it is tall enough
    // to hold the old offset — or until the user takes over.
    let frame = 0;
    let cancelled = false;
    const deadline = Date.now() + RESTORE_TIMEOUT_MS;
    const stop = () => {
      cancelled = true;
    };
    const step = () => {
      if (cancelled) return;
      const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      if (max >= y - 1 || Date.now() > deadline) {
        window.scrollTo(0, Math.min(y, max));
        return;
      }
      window.scrollTo(0, Math.min(y, max));
      frame = requestAnimationFrame(step);
    };
    window.addEventListener('wheel', stop, { passive: true, once: true });
    window.addEventListener('touchstart', stop, { passive: true, once: true });
    step();
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      window.removeEventListener('wheel', stop);
      window.removeEventListener('touchstart', stop);
    };
  }, [key, pathname, navType]);

  return null;
}
