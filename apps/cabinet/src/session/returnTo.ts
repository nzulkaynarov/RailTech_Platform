/**
 * Куда вернуть после входа (NOTIFY-1): ссылка из письма ведёт на страницу кабинета (`/profile#notifications`), а сессии
 * нет — `RequireSession` запоминает адрес, вход по ссылке из письма (часто в новой вкладке) или по коду приходит на `/`,
 * и `HomeRedirect` отправляет туда, где человек был. localStorage — вкладки письма и кабинета разные; срок — час,
 * одноразово. Хранилище недоступно — обычный вход на первый раздел.
 */
const KEY = 'rt-cab-return-to';
const TTL_MS = 60 * 60 * 1000;

interface Saved {
  path: string;
  at: number;
}

/** Только свой адрес: путь кабинета, не `//host` и не служебные страницы входа. */
function allowed(path: string): boolean {
  return path.startsWith('/') && !path.startsWith('//') && path !== '/' && !path.startsWith('/login') && !path.startsWith('/auth');
}

export function rememberReturnTo(path: string, now: number = Date.now()): void {
  if (!allowed(path)) return;
  try {
    localStorage.setItem(KEY, JSON.stringify({ path, at: now } satisfies Saved));
  } catch {
    // нет хранилища — после входа на первый раздел
  }
}

export function readReturnTo(now: number = Date.now()): string | null {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Saved | null;
    if (!saved || typeof saved.path !== 'string' || !allowed(saved.path) || now - saved.at > TTL_MS) return null;
    return saved.path;
  } catch {
    return null;
  }
}

export function clearReturnTo(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // нечего чистить
  }
}
