import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor, within } from '@testing-library/react';

import { CategoriesSettings } from '@/components/Settings/CategoriesSettings';
import { renderWithProviders } from '@/test/renderWithProviders';
import { toast } from 'sonner';

const { mockCategories, createMutMock, updateMutMock, deleteMutMock } = vi.hoisted(() => ({
  mockCategories: [
    {
      id: 1,
      name: 'Оборудование',
      parent: null,
      parent_name: null,
      domain_type: 1,
      domain_type_name: 'Товары',
      sort_order: 10,
      is_active: true,
    },
    {
      id: 2,
      name: 'Запасные части',
      parent: null,
      parent_name: null,
      domain_type: 1,
      domain_type_name: 'Товары',
      sort_order: 20,
      is_active: true,
    },
    {
      id: 3,
      name: 'Подшипники',
      parent: 2,
      parent_name: 'Запасные части',
      domain_type: 1,
      domain_type_name: 'Товары',
      sort_order: 30,
      is_active: true,
    },
  ],
  createMutMock: vi.fn(),
  updateMutMock: vi.fn(),
  deleteMutMock: vi.fn(),
}));

vi.mock('@/hooks/useCatalog', () => ({
  useCategories: () => ({
    data: mockCategories,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useDomainTypes: () => ({
    data: [{ id: 1, name: 'Товары' }],
    isLoading: false,
  }),
  useCreateCategory: () => ({ mutateAsync: createMutMock, isPending: false }),
  useUpdateCategory: () => ({ mutateAsync: updateMutMock, isPending: false }),
  useDeleteCategory: () => ({ mutateAsync: deleteMutMock, isPending: false }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe('CategoriesSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('рендерит список категорий с фильтром и кнопкой добавления', () => {
    renderWithProviders(<CategoriesSettings />);

    expect(screen.getByText('Категории каталога')).toBeInTheDocument();
    expect(screen.getByText('Оборудование')).toBeInTheDocument();
    expect(screen.getAllByText('Запасные части').length).toBeGreaterThan(0); // и строка, и «родитель» у Подшипников
    expect(screen.getByRole('button', { name: /Новая категория/i })).toBeInTheDocument();
  });

  it('счётчик показывает число категорий, а не «{{count}}» (FIX-4xb)', () => {
    renderWithProviders(<CategoriesSettings />);

    expect(screen.getByRole('status')).toHaveTextContent('Показано категорий: 3');
  });

  it('фильтрует категории по поисковому запросу', () => {
    renderWithProviders(<CategoriesSettings />);

    const input = screen.getByPlaceholderText(/Поиск категорий/i);
    fireEvent.change(input, { target: { value: 'Запасные' } });

    expect(screen.getByText('Запасные части')).toBeInTheDocument();
    expect(screen.queryByText('Оборудование')).not.toBeInTheDocument();
  });

  it('открывает диалог создания новой категории', async () => {
    renderWithProviders(<CategoriesSettings />);

    fireEvent.click(screen.getByRole('button', { name: /Новая категория/i }));

    await waitFor(() => {
      expect(screen.getByText('Создание категории')).toBeInTheDocument();
    });
  });

  it('категория с подкатегориями: диалог называет их и не даёт удалить (FIX-42)', async () => {
    renderWithProviders(<CategoriesSettings />);

    const row = screen.getAllByText('Запасные части', { selector: 'td' })[0].closest('tr')!;
    fireEvent.click(within(row).getByRole('button', { name: 'Удалить' }));

    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText(/пока в ней есть подкатегории: Подшипники/)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Удалить' })).toBeDisabled();
    expect(deleteMutMock).not.toHaveBeenCalled();
  });

  it('лист удаляется; отказ бэкенда CATEGORY_HAS_CHILDREN показывается понятным текстом', async () => {
    deleteMutMock.mockRejectedValueOnce({ response: { data: { detail: 'CATEGORY_HAS_CHILDREN' } } });
    renderWithProviders(<CategoriesSettings />);

    const row = screen.getByText('Оборудование', { selector: 'td' }).closest('tr')!;
    fireEvent.click(within(row).getByRole('button', { name: 'Удалить' }));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Удалить' }));

    await waitFor(() => expect(deleteMutMock).toHaveBeenCalledWith(1));
    await waitFor(() =>
      // translateApiError идёт через глобальный i18n (в jsdom — en), а не через провайдер теста.
      expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/subcategories|подкатегории/)),
    );
  });
});
