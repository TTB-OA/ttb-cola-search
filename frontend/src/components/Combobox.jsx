import { useEffect, useId, useRef, useState } from 'react';

/**
 * Text input with a suggestion list. The caller owns the options, so the same
 * control serves both a client-filtered vocabulary and a server typeahead.
 *
 * Options are `{ value, label, hint }`. Free text is always allowed: picking a
 * suggestion is a shortcut, not a requirement.
 */
export default function Combobox({
  value,
  onChange,
  onPick,
  options = [],
  loading = false,
  placeholder,
  className = 'input',
  emptyText = 'No matches',
  ariaLabel,
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const listId = useId();
  const wrapRef = useRef(null);

  // A new option set invalidates the highlighted row.
  useEffect(() => setActive(-1), [options]);

  useEffect(() => {
    function onPointerDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, []);

  const show = open && (loading || options.length > 0);

  function choose(opt) {
    setOpen(false);
    setActive(-1);
    if (onPick) onPick(opt);
    else onChange(opt.value);
  }

  function onKeyDown(e) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!options.length) return;
      e.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const step = e.key === 'ArrowDown' ? 1 : -1;
      setActive((i) => (i + step + options.length) % options.length);
    } else if (e.key === 'Enter' && open && active >= 0 && options[active]) {
      // Only swallow Enter while a suggestion is highlighted, so the form's own
      // submit-on-Enter still works.
      e.preventDefault();
      choose(options[active]);
    } else if (e.key === 'Escape' && open) {
      e.stopPropagation();
      setOpen(false);
    }
  }

  return (
    <div className="cbx" ref={wrapRef}>
      <input
        className={className}
        type="text"
        role="combobox"
        autoComplete="off"
        aria-expanded={show}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={show && active >= 0 ? `${listId}-${active}` : undefined}
        aria-label={ariaLabel}
        placeholder={placeholder}
        value={value || ''}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {show && (
        <ul className="cbx-list" id={listId} role="listbox">
          {loading ? (
            <li className="cbx-empty">Searching…</li>
          ) : options.length ? (
            options.map((o, i) => (
              <li
                key={o.key || o.value}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                className={'cbx-opt' + (i === active ? ' on' : '')}
                onMouseEnter={() => setActive(i)}
                // Keep focus on the input so blur doesn't close the list first.
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(o)}
              >
                <span className="cbx-label">{o.label}</span>
                {o.hint && <span className="cbx-hint">{o.hint}</span>}
              </li>
            ))
          ) : (
            <li className="cbx-empty">{emptyText}</li>
          )}
        </ul>
      )}
    </div>
  );
}

/** Client-side match over a fixed vocabulary, prefix hits first. */
export function matchOptions(list, term, limit = 10) {
  const t = (term || '').trim().toLowerCase();
  if (!t) return list.slice(0, limit).map((v) => ({ value: v, label: v }));
  const starts = [];
  const contains = [];
  for (const v of list) {
    const i = v.toLowerCase().indexOf(t);
    if (i === 0) starts.push(v);
    else if (i > 0) contains.push(v);
    if (starts.length >= limit) break;
  }
  return [...starts, ...contains].slice(0, limit).map((v) => ({ value: v, label: v }));
}
