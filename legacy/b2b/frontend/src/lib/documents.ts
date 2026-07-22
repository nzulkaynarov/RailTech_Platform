import { apiClient } from '@/api/client';

// ARCH-03: document PDFs render off-thread — a fetch that races ahead of the Celery task
// gets 202 + Retry-After and is polled here. ~15 × 2s ≈ 30s ceiling.
const PDF_POLL_MAX_ATTEMPTS = 15;
const PDF_POLL_DEFAULT_RETRY_SECONDS = 2;

/**
 * Fetch a private document as a Blob through an authenticated streaming endpoint, polling
 * through the ARCH-03 202/GENERATING window. Shared primitive behind every export/share
 * action (download / preview / print) so they all handle the off-thread render identically.
 *
 * Private documents (contract/invoice/act/КП PDFs) must NOT be linked via their raw
 * `/media/…` URL — on prod Django does not serve private MEDIA, so those 404. The backend
 * exposes streaming actions (`…/download-pdf/`, `crm/quotes/<id>/export/`) that this fetches.
 */
export async function fetchDocumentBlob(path: string, params?: Record<string, string>): Promise<Blob> {
  for (let attempt = 0; attempt < PDF_POLL_MAX_ATTEMPTS; attempt++) {
    const response = await apiClient.get(path, { params, responseType: 'blob' });
    if (response.status !== 202) {
      return new Blob([response.data], { type: response.data?.type || 'application/octet-stream' });
    }
    const retryAfter = Number(response.headers['retry-after']) || PDF_POLL_DEFAULT_RETRY_SECONDS;
    await new Promise((resolve) => setTimeout(resolve, retryAfter * 1000));
  }
  throw new Error('PDF_GENERATING_TIMEOUT');
}

/** Save a blob to disk as `filename` (the classic anchor[download] trick). */
export function saveBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

/**
 * Print a PDF blob via a hidden iframe (prints without navigating away). Falls back to opening
 * the blob in a new tab (where the user can print manually) if the iframe print can't fire.
 */
export function printBlob(blob: Blob): void {
  const url = window.URL.createObjectURL(blob);
  const iframe = document.createElement('iframe');
  iframe.style.position = 'fixed';
  iframe.style.right = '0';
  iframe.style.bottom = '0';
  iframe.style.width = '0';
  iframe.style.height = '0';
  iframe.style.border = '0';
  iframe.onload = () => {
    try {
      iframe.contentWindow?.focus();
      iframe.contentWindow?.print();
    } catch {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
    // Give the print dialog time to grab the document before teardown.
    window.setTimeout(() => {
      iframe.remove();
      window.URL.revokeObjectURL(url);
    }, 60_000);
  };
  iframe.src = url;
  document.body.appendChild(iframe);
}

/**
 * Build the public no-login document URL from the share token, mirroring the backend public КП
 * URL ({origin}/api/v1/public/documents/{token}/). Returns null when the token is not exposed
 * (draft / cancelled / backend not yet updated), so callers can hide the «Копировать ссылку» item.
 */
export function publicDocumentUrl(token: string | null | undefined, origin: string): string | null {
  if (!token) return null;
  return `${origin}/api/v1/public/documents/${token}/`;
}

/** Best-effort parse of an axios-blob error into its `{"detail": CODE}` code (DRF error shape). */
export async function extractBlobErrorCode(err: unknown): Promise<string> {
  const data = (err as { response?: { data?: unknown } })?.response?.data;
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text()) as { detail?: string };
      return parsed.detail || '';
    } catch {
      /* not JSON */
    }
  }
  return '';
}
