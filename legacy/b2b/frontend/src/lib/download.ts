import { apiClient } from '@/api/client';

/**
 * Download a private file through an authenticated streaming endpoint.
 *
 * Private documents (contract/invoice/act PDFs, KYC docs) must NOT be linked via
 * their raw `pdf_url` / `.url` (= `/media/…`): on prod there is no MinIO and Django
 * does not serve private MEDIA paths, so those URLs 404. The backend exposes
 * `…/download-pdf/` (and `…/download-document/{id}/`) actions that stream the bytes
 * with auth + tenant checks; this helper fetches them as a blob and saves the file.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const response = await apiClient.get(path, { responseType: 'blob' });
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
