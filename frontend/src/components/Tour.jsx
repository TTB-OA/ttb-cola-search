// Dependency-free spotlight tour: dims the page, cuts a highlight around the
// step's target element, and anchors a popover next to it.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Icon from './Icon.jsx';
import { api } from '../lib/api.js';
import { TOUR_STEPS, hasSeenTour, markTourSeen } from '../lib/tour.js';

const TourContext = createContext({ active: false, start: () => {} });

export function useTour() {
  return useContext(TourContext);
}

const GAP = 14;
const PAD = 8;
const POP_W = 360;

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function findTarget(step) {
  if (!step || !step.target) return null;
  const el = document.querySelector(step.target);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width >= 4 && r.height >= 4 ? el : null;
}

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

// Pick the first placement that fits, falling back to a centered popover.
function placePopover(rect, prefer, popW, popH) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const centered = { top: (vh - popH) / 2, left: (vw - popW) / 2, side: 'center' };
  if (!rect) return centered;

  const fits = {
    bottom: rect.bottom + GAP + popH + 8 <= vh,
    top: rect.top - GAP - popH - 8 >= 0,
    right: rect.right + GAP + popW + 8 <= vw,
    left: rect.left - GAP - popW - 8 >= 0,
  };
  const side = [prefer, 'bottom', 'top', 'right', 'left'].find((p) => fits[p]);
  if (!side) {
    // Nothing fits: use whichever of above/below has more room, clamped on screen.
    const below = vh - rect.bottom;
    const useBelow = below >= rect.top;
    return {
      top: useBelow
        ? clamp(rect.bottom + GAP, 12, Math.max(12, vh - popH - 12))
        : clamp(rect.top - GAP - popH, 12, Math.max(12, vh - popH - 12)),
      left: clamp(rect.left + rect.width / 2 - popW / 2, 12, Math.max(12, vw - popW - 12)),
      side: useBelow ? 'bottom' : 'top',
    };
  }

  if (side === 'bottom' || side === 'top') {
    return {
      top: side === 'bottom' ? rect.bottom + GAP : rect.top - GAP - popH,
      left: clamp(rect.left + rect.width / 2 - popW / 2, 12, Math.max(12, vw - popW - 12)),
      side,
    };
  }
  return {
    top: clamp(rect.top + rect.height / 2 - popH / 2, 12, Math.max(12, vh - popH - 12)),
    left: side === 'right' ? rect.right + GAP : rect.left - GAP - popW,
    side,
  };
}

function sameBox(a, b) {
  if (!a || !b) return a === b;
  return (
    Math.abs(a.top - b.top) < 0.5 &&
    Math.abs(a.left - b.left) < 0.5 &&
    Math.abs(a.width - b.width) < 0.5 &&
    Math.abs(a.height - b.height) < 0.5
  );
}

function TourOverlay({ steps, index, onNext, onPrev, onClose }) {
  const step = steps[index];
  const popRef = useRef(null);
  const readyRef = useRef(false);
  const scrolledRef = useRef(-1);
  const [ready, setReady] = useState(false);
  const [rect, setRect] = useState(null);
  const [pos, setPos] = useState(null);

  // A step may render before its page finishes loading, so hold the card back
  // until the target shows up (or we give up and center it).
  useEffect(() => {
    readyRef.current = false;
    setReady(false);
    setPos(null);
    const t = setTimeout(() => {
      readyRef.current = true;
      setReady(true);
    }, 2500);
    return () => clearTimeout(t);
  }, [index]);

  // Track target geometry (handles page transitions, smooth scrolling, resize).
  useEffect(() => {
    let frame = 0;
    let lastRect = null;
    let lastPos = null;

    const tick = () => {
      const el = findTarget(step);
      if (!readyRef.current && (el || !step.target)) {
        readyRef.current = true;
        setReady(true);
      }
      if (scrolledRef.current !== index && readyRef.current) {
        scrolledRef.current = index;
        const behavior = prefersReducedMotion() ? 'auto' : 'smooth';
        if (el) el.scrollIntoView({ behavior, block: 'center', inline: 'nearest' });
        else window.scrollTo({ top: 0, behavior });
      }
      const r = el ? el.getBoundingClientRect() : null;
      const next = r
        ? {
            top: r.top - PAD,
            left: r.left - PAD,
            width: r.width + PAD * 2,
            height: r.height + PAD * 2,
            bottom: r.bottom + PAD,
            right: r.right + PAD,
          }
        : null;
      if (!sameBox(next, lastRect)) {
        lastRect = next;
        setRect(next);
      }
      const pop = popRef.current;
      if (pop) {
        const p = placePopover(next, step.placement || 'bottom', pop.offsetWidth, pop.offsetHeight);
        if (!lastPos || Math.abs(p.top - lastPos.top) > 0.5 || Math.abs(p.left - lastPos.left) > 0.5 || p.side !== lastPos.side) {
          lastPos = p;
          setPos(p);
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  // Keyboard: Esc closes, arrows/Enter navigate, Tab stays inside the popover.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        onNext();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        onPrev();
      } else if (e.key === 'Tab') {
        const pop = popRef.current;
        if (!pop) return;
        const items = pop.querySelectorAll('button:not([disabled])');
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        } else if (!pop.contains(document.activeElement)) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [onNext, onPrev, onClose]);

  useEffect(() => {
    if (popRef.current) popRef.current.focus({ preventScroll: true });
  }, [index]);

  const last = index === steps.length - 1;
  const shown = ready && pos;

  return (
    <div className="tour-root">
      <div className={'tour-blocker' + (rect && shown ? '' : ' dim')} onClick={onClose} aria-hidden="true" />
      {rect && shown && (
        <div
          className="tour-spot"
          aria-hidden="true"
          style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }}
        />
      )}
      <div
        className={'tour-pop' + (pos ? ' side-' + pos.side : '')}
        ref={popRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        tabIndex={-1}
        style={{
          width: Math.min(POP_W, window.innerWidth - 24),
          top: pos ? pos.top : 0,
          left: pos ? pos.left : 0,
          opacity: shown ? 1 : 0,
          pointerEvents: shown ? 'auto' : 'none',
        }}
      >
        <button className="tour-x" onClick={onClose} aria-label="Close tour">
          <Icon name="close" size={16} />
        </button>
        <div className="tour-step-count">
          Step {index + 1} of {steps.length}
        </div>
        <h3 id="tour-title" className="tour-title">
          {step.title}
        </h3>
        <p className="tour-body">{step.body}</p>
        <div className="tour-actions">
          <div className="tour-dots" aria-hidden="true">
            {steps.map((s, i) => (
              <span key={s.id} className={'tour-dot' + (i === index ? ' on' : '')} />
            ))}
          </div>
          <div className="tour-buttons">
            {index > 0 && (
              <button className="btn ghost sm" onClick={onPrev}>
                Back
              </button>
            )}
            {!last && (
              <button className="linkbtn tour-skip" onClick={onClose}>
                Skip
              </button>
            )}
            <button className="btn sm" onClick={last ? onClose : onNext}>
              {last ? 'Done' : 'Next'}
              {!last && <Icon name="chevRight" size={16} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function TourProvider({ children }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [steps, setSteps] = useState(null);
  const [index, setIndex] = useState(0);
  const [pending, setPending] = useState(false);
  const colaIdRef = useRef(undefined); // undefined = not fetched, null = unavailable
  const fetchingRef = useRef(false);

  // The tour opens on the home page, then walks the user through results and detail.
  const start = useCallback(() => {
    setPending(true);
    if (location.pathname !== '/') navigate('/');
  }, [location.pathname, navigate]);

  const stop = useCallback(() => {
    setPending(false);
    setSteps(null);
    markTourSeen();
  }, []);

  useEffect(() => {
    if (!hasSeenTour()) setPending(true);
  }, []);

  // Resolve step targets once the home page has rendered and we know whether a
  // sample record is available for the detail-page steps.
  useEffect(() => {
    if (!pending || location.pathname !== '/') return undefined;

    if (colaIdRef.current === undefined && !fetchingRef.current) {
      fetchingRef.current = true;
      api
        .searchColas({ sort: 'approvalDate', status: 'Approved', pageSize: 1, facets: false })
        .then((d) => {
          const first = d && d.items && d.items[0];
          colaIdRef.current = first ? first.id : null;
        })
        .catch(() => {
          colaIdRef.current = null;
        });
    }

    const isMobile = window.matchMedia('(max-width: 720px)').matches;
    let tries = 0;
    const id = setInterval(() => {
      tries += 1;
      const ready = colaIdRef.current !== undefined && findTarget({ target: '[data-tour="search-box"]' });
      if (!ready && tries <= 60) return;
      clearInterval(id);
      setPending(false);
      if (!ready) return;

      const ctx = { colaId: colaIdRef.current };
      const resolved = TOUR_STEPS.map((s) => ({
        ...s,
        route: typeof s.route === 'function' ? (ctx.colaId ? s.route(ctx) : null) : s.route,
      })).filter((s) => {
        if (s.route === null) return false; // dynamic route with no sample record
        if (s.skipMobile && isMobile) return false;
        if (s.requireTarget && !findTarget(s)) return false;
        return true;
      });
      setIndex(0);
      setSteps(resolved);
    }, 120);
    return () => clearInterval(id);
  }, [pending, location.pathname]);

  // Move to the page a step lives on before it is shown.
  useEffect(() => {
    if (!steps) return;
    const route = steps[index] && steps[index].route;
    if (!route) return;
    const path = route.split('?')[0];
    if (location.pathname !== path) navigate(route);
  }, [steps, index, location.pathname, navigate]);

  const next = useCallback(() => {
    setIndex((i) => {
      if (!steps) return i;
      return i + 1 >= steps.length ? i : i + 1;
    });
  }, [steps]);

  const prev = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);

  return (
    <TourContext.Provider value={{ active: !!steps, start }}>
      {children}
      {steps && <TourOverlay steps={steps} index={index} onNext={next} onPrev={prev} onClose={stop} />}
    </TourContext.Provider>
  );
}
