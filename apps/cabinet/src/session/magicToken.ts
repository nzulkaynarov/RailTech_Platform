/**
 * Токен входа живёт только в фрагменте ссылки `/auth/magic#token=…`. Telegram SDK (`telegram-web-app.js`
 * в `<head>`) при загрузке разбирает ВЕСЬ `location.hash` и кладёт параметры в
 * `sessionStorage['__telegram__initParams']` и в память `window.Telegram.WebView.initParams` — очистка
 * адресной строки этих копий не снимает. Поэтому:
 * 1. `index.html` до загрузки SDK забирает токен в `window.__cabinetMagicToken` и стирает фрагмент;
 * 2. страница входа дочищает SDK (`scrubTelegramToken`) — на случай, если фрагмент дошёл до SDK.
 */
const SDK_STORE_KEY = '__telegram__initParams';

type MagicWindow = Window & {
  __cabinetMagicToken?: string;
  Telegram?: { WebView?: { initParams?: Record<string, unknown> } };
};

let pending = '';

/** Токен из фрагмента (`#token=…`); пусто, если его нет. */
export function tokenFromHash(hash: string): string {
  return new URLSearchParams(hash.replace(/^#/, '')).get('token')?.trim() ?? '';
}

/**
 * Токен, пойманный скриптом `index.html` до запуска SPA. Читается один раз и забывается в `window`;
 * повторный вызов (StrictMode) возвращает то же значение до `clearPendingMagicToken`.
 */
export function consumePendingMagicToken(): string {
  const w = window as MagicWindow;
  if (w.__cabinetMagicToken) {
    pending = w.__cabinetMagicToken;
    delete w.__cabinetMagicToken;
  }
  return pending;
}

export function clearPendingMagicToken(): void {
  pending = '';
}

/** Снять `token` из копий SDK Telegram: sessionStorage (прочие параметры остаются) и память страницы. */
export function scrubTelegramToken(): void {
  try {
    const raw = window.sessionStorage.getItem(SDK_STORE_KEY);
    if (raw) {
      const params = JSON.parse(raw) as Record<string, unknown>;
      if ('token' in params) {
        delete params.token;
        window.sessionStorage.setItem(SDK_STORE_KEY, JSON.stringify(params));
      }
    }
  } catch {
    // Хранилище недоступно или не JSON — копии токена там нет.
  }
  const initParams = (window as MagicWindow).Telegram?.WebView?.initParams;
  if (initParams && 'token' in initParams) delete initParams.token;
}
