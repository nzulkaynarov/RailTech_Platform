import { useEffect, useState } from 'react';

/**
 * Returns `value` delayed by `delayMs`: it only updates after the input has been
 * stable for that long. Used to throttle keystroke-driven work (e.g. the catalog
 * typeahead search) so we fire one request per pause, not one per keypress.
 */
export function useDebouncedValue<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState<T>(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
