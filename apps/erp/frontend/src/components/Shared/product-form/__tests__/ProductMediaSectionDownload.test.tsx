/**
 * Документ товара — приватный (S0-9): загруженный файл скачивается через аутентифицированный эндпоинт,
 * а не по адресу `doc.file`; документ-ссылка открывается как внешний адрес.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { ProductMediaSection } from '../ProductMediaSection';
import { renderWithProviders } from '@/test/renderWithProviders';

const downloadFile = vi.fn().mockResolvedValue(undefined);
vi.mock('@/lib/download', () => ({ downloadFile: (...args: unknown[]) => downloadFile(...args) }));

const mutation = { mutateAsync: vi.fn(), isPending: false };
vi.mock('@/hooks/useCatalog', () => ({
  useProduct: () => ({
    data: {
      id: 12,
      images: [],
      documents: [
        { id: 5, name: 'Паспорт изделия', file: '/api/v1/catalog/products/12/download-document/5/', file_url: null },
        { id: 6, name: 'Каталог поставщика', file: null, file_url: 'https://example.org/catalog.pdf' },
      ],
    },
  }),
  useUploadProductImage: () => mutation,
  useDeleteProductImage: () => mutation,
  useUploadProductDocument: () => mutation,
  useDeleteProductDocument: () => mutation,
}));

describe('скачивание документов товара', () => {
  beforeEach(() => {
    downloadFile.mockClear();
  });

  it('загруженный файл скачивается через эндпоинт скачивания', async () => {
    renderWithProviders(<ProductMediaSection productId={12} />);

    const buttons = screen.getAllByRole('button', { name: 'Скачать' });
    fireEvent.click(buttons[0]);

    await waitFor(() =>
      expect(downloadFile).toHaveBeenCalledWith('catalog/products/12/download-document/5/', 'Паспорт изделия'),
    );
  });

  it('документ-ссылка открывается во внешнем адресе, а не через сервер', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    renderWithProviders(<ProductMediaSection productId={12} />);

    const buttons = screen.getAllByRole('button', { name: 'Скачать' });
    fireEvent.click(buttons[1]);

    expect(open).toHaveBeenCalledWith('https://example.org/catalog.pdf', '_blank', 'noopener,noreferrer');
    expect(downloadFile).not.toHaveBeenCalled();
    open.mockRestore();
  });
});
