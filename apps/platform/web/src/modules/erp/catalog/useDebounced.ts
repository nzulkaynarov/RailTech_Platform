import { useEffect, useState } from "react";

/** Значение, которое обновляется не чаще раза в 300 мс (поиск по мере ввода не засыпает BFF запросами). */
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(value);
    }, delay);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value, delay]);
  return debounced;
}
