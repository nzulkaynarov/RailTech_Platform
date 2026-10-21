/**
 * HTTP-слой для клиента orval (apps/platform/docs/03-frontend.md §7). Сессия — httpOnly-cookie
 * `rt_pf_session`, браузер её не читает; мутации несут `X-CSRF-Token` из cookie `rt_pf_csrf`
 * (double submit, контракт platform-bff.yaml). 401 `SESSION_EXPIRED` сообщается подписчикам —
 * экран входа появится в фазе P1.
 */
import { ApiError, toApiError } from "./errors";

const CSRF_COOKIE = "rt_pf_csrf";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

type Listener = () => void;
const sessionExpiredListeners = new Set<Listener>();

export function onSessionExpired(listener: Listener): () => void {
  sessionExpiredListeners.add(listener);
  return () => sessionExpiredListeners.delete(listener);
}

function readCookie(name: string): string | null {
  for (const part of document.cookie.split("; ")) {
    const [key, ...rest] = part.split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

function withSession(options: RequestInit): RequestInit {
  const headers = new Headers(options.headers);
  const method = (options.method ?? "GET").toUpperCase();
  const csrf = SAFE_METHODS.has(method) ? null : readCookie(CSRF_COOKIE);
  if (csrf) headers.set("X-CSRF-Token", csrf);
  return { ...options, headers, credentials: "same-origin" };
}

async function parse(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const type = response.headers.get("content-type") ?? "";
  return type.includes("application/json") ? response.json() : response.text();
}

/**
 * Мутатор orval: возвращает тело успешного ответа (`override.fetch.includeHttpResponseReturnType:
 * false`), при ошибке бросает `ApiError`. Кэш TanStack Query хранит DTO как есть.
 */
export const http = async <T>(url: string, options: RequestInit): Promise<T> => {
  const response = await fetch(url, withSession(options));
  const data = await parse(response);
  if (!response.ok) {
    const error = toApiError(response.status, data);
    if (response.status === 401 && error.code === "SESSION_EXPIRED") {
      for (const listener of sessionExpiredListeners) listener();
    }
    throw error;
  }
  return data as T;
};

/** Тип ошибки сгенерированных хуков: orval подставляет `ErrorType<Body>` вместо типа тела ошибки. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- сигнатуру задаёт orval
export type ErrorType<_Body> = ApiError;
