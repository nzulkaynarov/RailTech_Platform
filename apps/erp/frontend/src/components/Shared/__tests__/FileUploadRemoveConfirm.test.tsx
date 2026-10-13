/**
 * Инвариант волны U4: **необратимое действие спрашивает подтверждение.**
 *
 * Аудит UI 2026-07-30 нашёл 11 таких действий, срабатывавших с первого клика; удаление
 * файла — самое опасное из них, потому что корзина стоит в узкой строке списка и
 * восстановить файл из интерфейса нельзя.
 */

import { describe, it, expect, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { FileUpload } from '../FileUpload';
import { renderWithProviders } from '@/test/renderWithProviders';

const FILES = [{ id: 7, name: 'Договор.pdf', url: '/media/x.pdf' }];

describe('удаление файла требует подтверждения', () => {
  it('первый клик по корзине НЕ удаляет, а открывает вопрос', async () => {
    const onRemove = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<FileUpload files={FILES} onRemove={onRemove} onUpload={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Удалить' }));

    expect(await screen.findByText('Удалить файл?')).toBeInTheDocument();
    expect(onRemove).not.toHaveBeenCalled();
  });

  it('удаление происходит только после подтверждения', async () => {
    const onRemove = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<FileUpload files={FILES} onRemove={onRemove} onUpload={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Удалить' }));
    await screen.findByText('Удалить файл?');
    // Подтверждающая кнопка живёт внутри диалога и подписана тем же словом.
    const dialog = await screen.findByRole('dialog');
    const confirm = Array.from(dialog.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === 'Удалить',
    );
    expect(confirm).toBeDefined();
    fireEvent.click(confirm as HTMLElement);

    await waitFor(() => expect(onRemove).toHaveBeenCalledWith(7));
  });

  it('отказ от подтверждения оставляет файл на месте', async () => {
    const onRemove = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<FileUpload files={FILES} onRemove={onRemove} onUpload={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Удалить' }));
    await screen.findByText('Удалить файл?');
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));

    await waitFor(() => expect(screen.queryByText('Удалить файл?')).not.toBeInTheDocument());
    expect(onRemove).not.toHaveBeenCalled();
  });
});
