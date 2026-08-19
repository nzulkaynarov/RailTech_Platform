import { useCallback, useSyncExternalStore } from 'react';

/**
 * Router-free URL query-state helper.
 *
 * The Platform Admin SPA does NOT mount a Router provider; direct history
 * manipulation is the portable way to drive list-table URL state (search,
 * tab, sort, page) while keeping shareable links and browser back/forward.
 *
 * ОДИН источник на всё приложение. До 19-08 каждый вызов хука держал СВОЁ состояние
 * (`useState` + `forceTick`), и перерисовывался только тот экземпляр, который сам записал URL.
 * В админ-реестрах это ломало главное: таблица (`AdminDataTable`) писала `?…q=…` своим
 * экземпляром, а страница, которая собирает параметры запроса к API, держала ДРУГОЙ экземпляр
 * и об изменении не узнавала — поиск и вкладки-фильтры меняли адресную строку и подсветку, но
 * список оставался прежним и запрос не уходил вовсе. Оператор делал вывод «такой записи нет».
 *
 * Лечение — внешнее хранилище: подписчики общие, `set` уведомляет ВСЕХ. `useSyncExternalStore`
 * берётся не для красоты: он даёт согласованный снимок при конкурентном рендере, а снимок здесь
 * — строка `location.search`, поэтому сравнение по значению работает без лишних перерисовок.
 */
const listeners = new Set<() => void>();

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange);
  window.addEventListener('popstate', onStoreChange);
  return () => {
    listeners.delete(onStoreChange);
    window.removeEventListener('popstate', onStoreChange);
  };
}

function emit(): void {
  for (const listener of listeners) listener();
}

function getSearchSnapshot(): string {
  return typeof window === 'undefined' ? '' : window.location.search;
}

/** На сервере/в тестах без window снимок пуст — хук остаётся вызываемым. */
function getServerSnapshot(): string {
  return '';
}

export function useUrlState() {
  const search = useSyncExternalStore(subscribe, getSearchSnapshot, getServerSnapshot);

  const get = useCallback((key: string): string => new URLSearchParams(search).get(key) ?? '', [search]);

  const set = useCallback((entries: Record<string, string | null | undefined>) => {
    const params = new URLSearchParams(getSearchSnapshot());
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
    emit();
  }, []);

  return { get, set };
}
