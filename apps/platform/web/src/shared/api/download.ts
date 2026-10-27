import { toApiError } from "./errors";

/** Имя файла из `Content-Disposition: attachment; filename="leads-20261026-1430.csv"`. */
export function filenameFrom(disposition: string | null, fallback: string): string {
  const match = disposition ? /filename="?([^";]+)"?/i.exec(disposition) : null;
  return match?.[1] ?? fallback;
}

/**
 * Скачивание файла из BFF (выгрузка CSV): запрос с cookie сессии, ошибка BFF — `ApiError` (как у остальных вызовов),
 * успех — файл сохраняется браузером под именем из `Content-Disposition` (имя содержит дату). BFF отдаёт файл потоком;
 * в браузере он собирается в `Blob` — выгрузка не больше 10 000 строк.
 */
export async function downloadFile(url: string, fallbackName: string): Promise<string> {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = undefined;
    }
    throw toApiError(response.status, body);
  }
  const name = filenameFrom(response.headers.get("content-disposition"), fallbackName);
  const blob = await response.blob();
  const link = document.createElement("a");
  const href = URL.createObjectURL(blob);
  link.href = href;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
  return name;
}
