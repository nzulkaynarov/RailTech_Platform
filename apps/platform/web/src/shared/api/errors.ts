/** Ошибка BFF в формате `Error` контракта (platform-bff.yaml): код, текст, источник, детали. */
export type ErrorSource = "bff" | "crm" | "erp" | "eds";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly source: ErrorSource;
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    source: ErrorSource = "bff",
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.source = source;
    this.details = details;
  }
}

/** Из тела ответа BFF; не-JSON и чужие формы (прокси, 502) получают код `HTTP_ERROR`. */
export function toApiError(status: number, body: unknown): ApiError {
  if (body && typeof body === "object" && "code" in body && "message" in body) {
    const b = body as {
      code: string;
      message: string;
      source?: ErrorSource;
      details?: Record<string, unknown>;
    };
    return new ApiError(status, b.code, b.message, b.source ?? "bff", b.details ?? {});
  }
  return new ApiError(status, "HTTP_ERROR", `HTTP ${String(status)}`);
}
