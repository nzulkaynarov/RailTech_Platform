/**
 * HTTP-слой для клиента orval (SPEC §10.3, §11).
 * Access-токен живёт только в памяти; refresh — httpOnly cookie, обновляется
 * автоматически при 401 (один раз на запрос, параллельные запросы ждут один refresh).
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Listener = (token: string | null) => void;

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<Listener>();

export const tokenStore = {
  get: (): string | null => accessToken,
  set(token: string | null): void {
    accessToken = token;
    for (const listener of listeners) listener(token);
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

export async function refreshAccess(): Promise<boolean> {
  refreshing ??= (async () => {
    // Токен на момент старта: если за время запроса пользователь вошёл заново,
    // неуспешный refresh не должен затирать новый токен (гонка «check → login»).
    const before = accessToken;
    try {
      const response = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "same-origin",
      });
      if (!response.ok) {
        if (accessToken === before) tokenStore.set(null);
        return accessToken !== null;
      }
      const body = (await response.json()) as { access_token: string };
      tokenStore.set(body.access_token);
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

function withAuth(options: RequestInit): RequestInit {
  const headers = new Headers(options.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return { ...options, headers, credentials: "same-origin" };
}

async function parse(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const type = response.headers.get("content-type") ?? "";
  return type.includes("application/json") ? response.json() : response.text();
}

function toError(status: number, body: unknown): ApiError {
  if (body && typeof body === "object" && "code" in body) {
    const b = body as { code: string; message?: string; details?: Record<string, unknown> };
    return new ApiError(status, b.code, b.message ?? b.code, b.details ?? {});
  }
  if (status === 422) return new ApiError(status, "validation_failed", "Проверьте поля формы");
  return new ApiError(status, "http_error", `HTTP ${String(status)}`);
}

export async function rawFetch(url: string, options: RequestInit = {}): Promise<Response> {
  let response = await fetch(url, withAuth(options));
  const isAuthCall = url.startsWith("/api/v1/auth/");
  if (response.status === 401 && !isAuthCall && (await refreshAccess())) {
    response = await fetch(url, withAuth(options));
  }
  return response;
}

/**
 * Мутатор orval: возвращает тело успешного ответа (`override.fetch.includeHttpResponseReturnType:
 * false`), при ошибке бросает `ApiError`. Кэш TanStack Query хранит DTO как есть.
 */
export const http = async <T>(url: string, options: RequestInit): Promise<T> => {
  const response = await rawFetch(url, options);
  const data = await parse(response);
  if (!response.ok) throw toError(response.status, data);
  return data as T;
};

/**
 * Тип ошибки сгенерированных хуков: orval ищет `ErrorType<Body>` рядом с мутатором и подставляет
 * его вместо `ErrorOut`. Тело ошибки уже разобрано `http` в поля `ApiError`.
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- сигнатуру задаёт orval
export type ErrorType<_Body> = ApiError;

/** Скачать файл с авторизацией (ответ API — бинарный, не JSON). */
export async function downloadFile(url: string, filename: string): Promise<void> {
  const response = await rawFetch(url);
  if (!response.ok)
    throw new ApiError(response.status, "http_error", `HTTP ${String(response.status)}`);
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

/** Убрать пустые фильтры: клиент orval сериализует `null` как строку "null". */
export function compact<T extends object>(params: T): T {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== null && value !== undefined && value !== "",
    ),
  ) as T;
}
