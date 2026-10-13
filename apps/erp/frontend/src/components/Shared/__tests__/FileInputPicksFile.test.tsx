/**
 * «Выбрать файл» действительно загружает файл.
 *
 * `input.files` — ЖИВОЙ `FileList`, привязанный к полю: сброс `value` (нужный, чтобы повторный
 * выбор того же файла снова дал `change`) опустошает его. Оба компонента загрузки читали список
 * ПОСЛЕ сброса и потому шли по пустому — «Add image» и «click to select» молча не делали ничего:
 * ни запроса, ни тоста, ни ошибки. Фото товара загрузить было нельзя вообще, документы — только
 * перетаскиванием (drop читает dataTransfer, а не поле). Найдено прогоном глазами 19-08.
 *
 * Тест держит именно ПОРЯДОК: сначала снимок, потом сброс. Ломается молча — обработчик не падает,
 * просто цикл идёт по нулю элементов.
 */

import { describe, it, expect, vi } from 'vitest';
import { fireEvent, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { ImageGalleryUpload } from '../ImageGalleryUpload';
import { FileUpload } from '../FileUpload';

const png = () => new File([new Uint8Array([1, 2, 3])], 'photo.png', { type: 'image/png' });
const pdf = () => new File([new Uint8Array([1, 2, 3])], 'act.pdf', { type: 'application/pdf' });

function fileInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector('input[type="file"]');
  if (!input) throw new Error('поле выбора файла не найдено');
  return input as HTMLInputElement;
}

/**
 * jsdom подсовывает в `input.files` обычный массив, и очистка `value` его НЕ опустошает —
 * наивный тест зеленеет даже на сломанном порядке (проверено дважды). Эмулируем настоящую
 * связь браузера: `files` — ОДИН И ТОТ ЖЕ объект-список, который ОПУСТОШАЕТСЯ на месте, как
 * только полю присвоили пустое значение. Именно поэтому «сначала сброс, потом чтение» и
 * оставляло обработчик без файлов, хотя ссылка на список у него была.
 */
function attachLiveFiles(input: HTMLInputElement, files: File[]): void {
  const live: Record<number | string, unknown> = { length: files.length };
  files.forEach((file, index) => {
    live[index] = file;
  });
  live.item = (index: number) => (live[index] as File | undefined) ?? null;

  Object.defineProperty(input, 'files', { configurable: true, get: () => live as unknown as FileList });
  Object.defineProperty(input, 'value', {
    configurable: true,
    get: () => (live.length ? 'C:\\fakepath\\' + files[0].name : ''),
    set: (next: string) => {
      if (next !== '') return;
      // Браузер опустошает СУЩЕСТВУЮЩИЙ FileList — ссылка у обработчика остаётся, файлов нет.
      files.forEach((_, index) => {
        delete live[index];
      });
      live.length = 0;
    },
  });
}

describe('выбор файла через поле (не перетаскиванием)', () => {
  it('галерея товара: выбранное фото уходит в onUpload', async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined);
    const { container } = renderWithProviders(<ImageGalleryUpload images={[]} onUpload={onUpload} />);

    const input = fileInput(container);
    attachLiveFiles(input, [png()]);
    fireEvent.change(input);

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));
    expect(onUpload.mock.calls[0][0]).toBeInstanceOf(File);
    expect((onUpload.mock.calls[0][0] as File).name).toBe('photo.png');
    // первое фото становится главным — это отдельная договорённость галереи
    expect(onUpload.mock.calls[0][1]).toBe(true);
  });

  it('документы: выбранный файл уходит в onUpload', async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined);
    const { container } = renderWithProviders(<FileUpload files={[]} onUpload={onUpload} />);

    const input = fileInput(container);
    attachLiveFiles(input, [pdf()]);
    fireEvent.change(input);

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));
    expect((onUpload.mock.calls[0][0] as File).name).toBe('act.pdf');
  });

  it('поле очищается после выбора — повторный выбор ТОГО ЖЕ файла снова сработает', async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined);
    const { container } = renderWithProviders(<FileUpload files={[]} onUpload={onUpload} />);
    const input = fileInput(container);
    attachLiveFiles(input, [pdf()]);

    fireEvent.change(input);
    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));

    expect(input.value).toBe('');
  });
});
