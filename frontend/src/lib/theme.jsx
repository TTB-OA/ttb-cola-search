// Colour mode. The `data-theme` attribute on <html> is what the stylesheets and
// the map key off; this module only owns choosing it, remembering it, and
// telling React about it.
//
// index.html applies the attribute before the bundle loads so a reload in dark
// mode never flashes the light theme, which is why the initial state is read
// back off the document rather than recomputed here.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

const KEY = 'cola.theme';

const ThemeContext = createContext({ theme: 'light', setTheme: () => {}, toggle: () => {} });

function systemTheme() {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function storedTheme() {
  try {
    const value = localStorage.getItem(KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    // Storage can be blocked outright; the OS preference still works.
    return null;
  }
}

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(
    () => document.documentElement.dataset.theme || storedTheme() || systemTheme()
  );
  // Only a deliberate choice is persisted, so an untouched session keeps
  // following the OS instead of freezing on whatever it happened to open with.
  const [chosen, setChosen] = useState(() => storedTheme() != null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    // Native scrollbars, date pickers and form controls follow this.
    document.documentElement.style.colorScheme = theme;
  }, [theme]);

  useEffect(() => {
    if (chosen) return undefined;
    const query = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!query) return undefined;
    const onChange = (e) => setThemeState(e.matches ? 'dark' : 'light');
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, [chosen]);

  const setTheme = useCallback((next) => {
    setChosen(true);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // Not being able to remember it is not a reason to refuse the switch.
    }
    setThemeState(next);
  }, []);

  const value = useMemo(
    () => ({ theme, setTheme, toggle: () => setTheme(theme === 'dark' ? 'light' : 'dark') }),
    [theme, setTheme]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
