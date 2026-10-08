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

/** Мутатор orval: возвращает `{ data, status, headers }`, при ошибке бросает `ApiError`. */
export const http = async <T>(url: string, options: RequestInit): Promise<T> => {
  const response = await rawFetch(url, options);
  const data = await parse(response);
  if (!response.ok) throw toError(response.status, data);
  return { data, status: response.status, headers: response.headers } as T;
};

type Success<R> = R extends { status: 200 | 201 | 204; data: infer D } ? D : never;

/** Данные успешного ответа: ошибки `http` уже бросил как `ApiError`. */
export function unwrap<R extends { status: number; data: unknown }>(response: R): Success<R> {
  return response.data as Success<R>;
}
