import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';

import { CategoriesSettings } from '@/components/Settings/CategoriesSettings';
import { renderWithProviders } from '@/test/renderWithProviders';

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
    expect(screen.getByText('Запасные части')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Новая категория/i })).toBeInTheDocument();
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
});
