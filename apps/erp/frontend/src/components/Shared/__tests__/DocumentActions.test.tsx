import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DocumentActions } from '../DocumentActions';
import { renderWithProviders } from '@/test/renderWithProviders';
import * as documents from '@/lib/documents';

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('sonner', () => ({ toast }));

vi.mock('@/lib/documents', () => ({
  fetchDocumentBlob: vi.fn(),
  saveBlob: vi.fn(),
  printBlob: vi.fn(),
  extractBlobErrorCode: vi.fn(),
}));

const mocked = documents as unknown as {
  fetchDocumentBlob: ReturnType<typeof vi.fn>;
  saveBlob: ReturnType<typeof vi.fn>;
  extractBlobErrorCode: ReturnType<typeof vi.fn>;
};

describe('DocumentActions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.URL.createObjectURL = vi.fn(() => 'stub-blob-url');
    window.URL.revokeObjectURL = vi.fn();
  });

  const setup = (props = {}) =>
    renderWithProviders(
      <DocumentActions
        request={(format) => ({ path: `crm/contracts/7/download-pdf/`, params: { format } })}
        filenameBase="Contract_7"
        formats={['pdf', 'xlsx']}
        {...props}
      />,
    );

  it('downloads the chosen format through the shared blob fetch', async () => {
    const user = userEvent.setup();
    const blob = new Blob(['%PDF']);
    mocked.fetchDocumentBlob.mockResolvedValue(blob);
    setup();

    await user.click(screen.getByRole('button', { name: 'Экспорт' }));
    await user.click(await screen.findByText('Скачать PDF'));

    await waitFor(() => expect(mocked.fetchDocumentBlob).toHaveBeenCalledWith('crm/contracts/7/download-pdf/', { format: 'pdf' }));
    await waitFor(() => expect(mocked.saveBlob).toHaveBeenCalledWith(blob, 'Contract_7.pdf'));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('opens an inline preview by navigating a synchronously-opened tab', async () => {
    const user = userEvent.setup();
    // The tab must be opened synchronously (within the click gesture) so the popup blocker
    // doesn't kill it after the await — assert window.open fired and the tab was navigated.
    const fakeWindow = { location: { href: '' }, close: vi.fn() };
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(fakeWindow as unknown as Window);
    mocked.fetchDocumentBlob.mockResolvedValue(new Blob(['%PDF']));
    setup();

    await user.click(screen.getByRole('button', { name: 'Экспорт' }));
    await user.click(await screen.findByText('Просмотр'));

    await waitFor(() => expect(openSpy).toHaveBeenCalledWith('', '_blank'));
    await waitFor(() => expect(fakeWindow.location.href).toBe('stub-blob-url'));
    openSpy.mockRestore();
  });

  it('surfaces the specific server refusal code (not a generic error)', async () => {
    const user = userEvent.setup();
    mocked.fetchDocumentBlob.mockRejectedValue({ response: { data: new Blob(['{"detail":"QUOTE_BELOW_COST"}']) } });
    mocked.extractBlobErrorCode.mockResolvedValue('QUOTE_BELOW_COST');
    setup();

    await user.click(screen.getByRole('button', { name: 'Экспорт' }));
    await user.click(await screen.findByText('Скачать PDF'));

    await waitFor(() => expect(mocked.extractBlobErrorCode).toHaveBeenCalled());
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(mocked.saveBlob).not.toHaveBeenCalled();
  });
});
