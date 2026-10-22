export const DEFAULT_HOME = "/dashboard/queue";

/** Адрес возврата после входа — только путь внутри Платформы (не `//host`, не `https://…`, не сам экран входа). */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return DEFAULT_HOME;
  }
  if (next === "/" || next.startsWith("/login")) return DEFAULT_HOME;
  return next;
}

export function loginPath(from: string): string {
  if (from === "/" || from === "") return "/login";
  return `/login?next=${encodeURIComponent(safeNext(from))}`;
}
