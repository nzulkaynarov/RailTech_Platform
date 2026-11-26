import { useCallback, useSyncExternalStore } from "react";

/**
 * Личные настройки всплывающих уведомлений (УВЕД-1) — хранятся в браузере по сотруднику, как раскладка боковых окон
 * (`panelsStore`): это настройка этого экрана, а не данные для других. Telegram-подписки — на сервере, в профиле.
 */
export interface NotifyPrefs {
  /** Всплывающие окна о новых уведомлениях */
  popups: boolean;
  /** Только те, что требуют действия */
  onlyAction: boolean;
  /** Уведомления браузера, когда вкладка в фоне (включает сотрудник одним щелчком) */
  browser: boolean;
}

export const DEFAULT_PREFS: NotifyPrefs = { popups: true, onlyAction: false, browser: false };

const prefsKey = (personId: string) => `rt-pf-notify-prefs:${personId}`;
const seenKey = (personId: string) => `rt-pf-notify-seen:${personId}`;

const listeners = new Set<() => void>();
const cache = new Map<string, { raw: string | null; value: NotifyPrefs }>();

function readRaw(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function readPrefs(personId: string): NotifyPrefs {
  const raw = readRaw(prefsKey(personId));
  const hit = cache.get(personId);
  if (hit && hit.raw === raw) return hit.value;
  let value = DEFAULT_PREFS;
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Partial<NotifyPrefs>;
      value = {
        popups: parsed.popups ?? DEFAULT_PREFS.popups,
        onlyAction: parsed.onlyAction ?? DEFAULT_PREFS.onlyAction,
        browser: parsed.browser ?? DEFAULT_PREFS.browser,
      };
    } catch {
      value = DEFAULT_PREFS;
    }
  }
  cache.set(personId, { raw, value });
  return value;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

export function useNotifyPrefs(
  personId: string,
): [NotifyPrefs, (patch: Partial<NotifyPrefs>) => void] {
  const prefs = useSyncExternalStore(
    subscribe,
    () => readPrefs(personId),
    () => DEFAULT_PREFS,
  );
  const update = useCallback(
    (patch: Partial<NotifyPrefs>) => {
      try {
        window.localStorage.setItem(
          prefsKey(personId),
          JSON.stringify({ ...readPrefs(personId), ...patch }),
        );
      } catch {
        // хранилище недоступно (приватное окно): настройка действует до перезагрузки
        cache.set(personId, { raw: null, value: { ...readPrefs(personId), ...patch } });
      }
      for (const listener of listeners) listener();
    },
    [personId],
  );
  return [prefs, update];
}

/** Время самого нового уже показанного уведомления (мс): после перезагрузки показанное не повторяется. */
export function readSeen(personId: string): number | null {
  const raw = readRaw(seenKey(personId));
  const value = raw === null ? Number.NaN : Number(raw);
  return Number.isFinite(value) ? value : null;
}

export function writeSeen(personId: string, at: number): void {
  try {
    window.localStorage.setItem(seenKey(personId), String(at));
  } catch {
    // без хранилища показанное повторится после перезагрузки — не критично
  }
}
