/** Страницы без входа и служебные: возвращаться на них после входа нельзя. */
const AUTH_PAGES = new Set(["/login", "/setup", "/change-password", "/sso/exchange"]);

/**
 * Безопасный адрес возврата после входа (`?to=`, его ставит Refine `CatchAllNavigate`).
 * Только путь внутри приложения: без схемы и хоста (`//evil`, `https:`), без обратной косой
 * черты и управляющих символов; сами страницы входа и корень — не адрес возврата (`null`).
 */
export function safeNextPath(raw: string | null | undefined): string | null {
  if (!raw?.startsWith("/") || raw.startsWith("//")) return null;
  // eslint-disable-next-line no-control-regex -- управляющие символы в адресе возврата недопустимы
  if (/[\\\u0000-\u001f\u007f]/.test(raw)) return null;
  const path = raw.split(/[?#]/)[0] ?? "";
  if (path === "/" || AUTH_PAGES.has(path)) return null;
  return raw;
}

/** Куда вести после шага входа: сохранённый адрес вместо «/», либо шаг смены пароля с тем же адресом. */
export function withNext(target: string, next: string | null): string {
  if (!next) return target;
  return target === "/" ? next : `${target}?to=${encodeURIComponent(next)}`;
}
