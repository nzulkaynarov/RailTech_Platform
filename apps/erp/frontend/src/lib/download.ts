import { apiClient } from '@/api/client';

// ARCH-03: document PDFs render off-thread — a download that races ahead of the
// Celery task gets 202 + Retry-After and is polled here. ~15 × 2s ≈ 30s ceiling.
const PDF_POLL_MAX_ATTEMPTS = 15;
const PDF_POLL_DEFAULT_RETRY_SECONDS = 2;

/**
 * Download a private file through an authenticated streaming endpoint.
 *
 * Private documents (contract/invoice/act PDFs, company files) must NOT be linked via
 * their raw `pdf_url` / `.url` (= `/media/…`): on prod there is no MinIO and Django
 * does not serve private MEDIA paths, so those URLs 404. The backend exposes
 * `…/download-pdf/` (and `…/download-document/{id}/`) actions that stream the bytes
 * with auth + tenant checks; this helper fetches them as a blob and saves the file.
 *
 * A 202 means the PDF is still rendering off-thread (ARCH-03) — retry after the
 * server's Retry-After hint until the file lands or the attempt budget runs out.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
  for (let attempt = 0; attempt < PDF_POLL_MAX_ATTEMPTS; attempt++) {
    const response = await apiClient.get(path, { responseType: 'blob' });
    if (response.status !== 202) {
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      return;
    }
    const retryAfter = Number(response.headers['retry-after']) || PDF_POLL_DEFAULT_RETRY_SECONDS;
    await new Promise((resolve) => setTimeout(resolve, retryAfter * 1000));
  }
  throw new Error('PDF_GENERATING_TIMEOUT');
}
