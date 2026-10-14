import { useCallback, useSyncExternalStore } from 'react';

/** Совпадает ли media-запрос сейчас; подписка на изменение (поворот телефона, ресайз окна). */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener?.('change', onChange);
      return () => list.removeEventListener?.('change', onChange);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** Десктопная раскладка списков (таблица) — от `lg`; ниже — карточки (телефон, планшет, Mini App). */
export const DESKTOP_QUERY = '(min-width: 1024px)';
