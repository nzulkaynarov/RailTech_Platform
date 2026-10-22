export const DEFAULT_HOME = "/dashboard/queue";

/** Адрес возврата после входа — только путь внутри Платформы (не `//host`, не `https://…`, не сам экран входа). */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return DEFAULT_HOME;
  }
  if (next === "/" || next.startsWith("/login")) return DEFAULT_HOME;
  return next;
}

/** Экран входа с возвратом на `from`; `expired` — сессия закончилась во время работы (показываем сообщение). */
export function loginPath(from: string, expired = false): string {
  const params = new URLSearchParams();
  if (from !== "/" && from !== "") params.set("next", safeNext(from));
  if (expired) params.set("reason", "expired");
  const query = params.toString();
  return query ? `/login?${query}` : "/login";
}
