import { getDocumentFile } from '@/api/portal';

/**
 * Скачивание документа `GET /documents/{id}/file` (по образцу B2B `lib/download.ts`): 202 — PDF ещё
 * рендерится в ERP (M2-ERP-03), повторяем через `Retry-After`, пока файл не будет готов или не кончится
 * бюджет попыток (≈ 30 с). Состояние «готовится» сообщается вызывающему, чтобы экран сказал об этом.
 */
export const DOWNLOAD_MAX_ATTEMPTS = 10;
const MAX_WAIT_SECONDS = 10;

export class DocumentNotReadyError extends Error {
  constructor() {
    super('DOCUMENT_NOT_READY');
    this.name = 'DocumentNotReadyError';
  }
}

export interface DownloadOptions {
  /** Вызывается на каждом 202 — экран показывает «документ готовится». */
  onPending?: (retryAfterSeconds: number) => void;
  /** Ожидание между попытками (тесты подменяют, чтобы не ждать секунды). */
  wait?: (ms: number) => Promise<void>;
  signal?: AbortSignal;
}

const timerWait = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));
let defaultWait: (ms: number) => Promise<void> = timerWait;

/** Тесты: не ждать `Retry-After` секундами (`null` — вернуть таймер). */
export function setDownloadWait(wait: ((ms: number) => Promise<void>) | null): void {
  defaultWait = wait ?? timerWait;
}

export async function downloadDocument(id: number, fallbackName: string, options: DownloadOptions = {}): Promise<void> {
  const wait = options.wait ?? defaultWait;
  for (let attempt = 0; attempt < DOWNLOAD_MAX_ATTEMPTS; attempt += 1) {
    if (options.signal?.aborted) return;
    const file = await getDocumentFile(id);
    if (file.state === 'ready') {
      saveBlob(file.blob, file.fileName ?? fallbackName);
      return;
    }
    options.onPending?.(file.retryAfterSeconds);
    await wait(Math.min(file.retryAfterSeconds, MAX_WAIT_SECONDS) * 1000);
  }
  throw new DocumentNotReadyError();
}

function saveBlob(blob: Blob, fileName: string): void {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.rel = 'noopener';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 0);
}
