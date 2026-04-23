import { useCallback, useEffect, useState } from 'react';

/**
 * Router-free URL query-state helper.
 *
 * The Platform Admin SPA does NOT mount a Router provider; direct history
 * manipulation is the portable way to drive list-table URL state (search,
 * tab, sort, page) while keeping shareable links and browser back/forward.
 */
function readQuery(): URLSearchParams {
  if (typeof window === 'undefined') return new URLSearchParams();
  return new URLSearchParams(window.location.search);
}

export function useUrlState() {
  const [, forceTick] = useState(0);

  useEffect(() => {
    const handler = () => forceTick((t) => t + 1);
    window.addEventListener('popstate', handler);
    return () => window.removeEventListener('popstate', handler);
  }, []);

  const get = useCallback((key: string): string => readQuery().get(key) ?? '', []);

  const set = useCallback((entries: Record<string, string | null | undefined>) => {
    const params = readQuery();
    let dirty = false;
    for (const [key, rawValue] of Object.entries(entries)) {
      const currentValue = params.get(key);
      if (rawValue == null || rawValue === '') {
        if (currentValue !== null) {
          params.delete(key);
          dirty = true;
        }
      } else if (rawValue !== currentValue) {
        params.set(key, rawValue);
        dirty = true;
      }
    }
    if (!dirty) return;
    const next = params.toString();
    const url =
      window.location.pathname + (next ? `?${next}` : '') + window.location.hash;
    window.history.replaceState({ ...(window.history.state || {}), url }, '', url);
    forceTick((t) => t + 1);
  }, []);

  return { get, set };
}
