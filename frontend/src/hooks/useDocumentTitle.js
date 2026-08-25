import { useEffect } from 'react';

export const SITE_TITLE = 'COLA Search — TTB Public Registry';

// Sets document.title to "<title> — COLA Search" for the life of the page,
// restoring the site title on unmount so a stale page name never lingers.
export function useDocumentTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} — COLA Search` : SITE_TITLE;
    return () => {
      document.title = SITE_TITLE;
    };
  }, [title]);
}
