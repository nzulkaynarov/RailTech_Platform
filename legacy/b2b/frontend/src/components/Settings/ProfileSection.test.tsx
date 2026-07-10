import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';

import { ProfileSection } from '@/components/Settings/ProfileSection';
import { accountsApi, type User } from '@/api/accountsApi';
import { useUserStore, type UserProfile } from '@/store/userStore';
import { renderWithProviders } from '@/test/renderWithProviders';

// Мокаем слой API-клиента (не сеть): handleSave компонента бьёт в этот mock.
vi.mock('@/api/accountsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/accountsApi')>();
  return {
    ...actual,
    accountsApi: {
      ...actual.accountsApi,
      updateMe: vi.fn(),
      uploadAvatar: vi.fn(),
      deleteAvatar: vi.fn(),
    },
  };
});

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const PROFILE: UserProfile = {
  firstName: 'Иван',
  lastName: 'Петров',
  patronymic: '',
  email: 'ivan@example.com',
  phone: '+998901234567',
  position: 'Менеджер',
  avatarInitials: 'ИП',
  avatarUrl: null,
};

function makeUser(): User {
  return {
    id: 1,
    username: 'ivan',
    email: 'ivan@example.com',
    first_name: 'Иван',
    last_name: 'Петров',
    phone: '+998901234567',
  };
}

describe('ProfileSection', () => {
  beforeEach(() => {
    vi.mocked(accountsApi.updateMe).mockReset();
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
    useUserStore.setState({ role: 'USER', profile: { ...PROFILE } });
  });

  it('рендерит двухколоночную секцию: заголовок, поля профиля и предпочтения', () => {
    renderWithProviders(<ProfileSection />);

    // Левая колонка (§2.4) — заголовок и описание секции из НОВЫХ ключей.
    expect(screen.getByRole('heading', { name: 'Личные данные' })).toBeInTheDocument();
    expect(
      screen.getByText('Имя, контакты и аватар — так вас видят коллеги и контрагенты'),
    ).toBeInTheDocument();

    // Поля предзаполнены из userStore; email read-only.
    expect(screen.getByLabelText('Фамилия')).toHaveValue('Петров');
    expect(screen.getByLabelText('Имя')).toHaveValue('Иван');
    expect(screen.getByLabelText('Email')).toBeDisabled();
    expect(screen.getByLabelText('Телефон')).toHaveValue('+998901234567');

    // Карточка предпочтений: язык и тема.
    expect(screen.getByText('Интерфейс')).toBeInTheDocument();
    expect(screen.getByText('Язык интерфейса')).toBeInTheDocument();
    expect(screen.getByText('Тема')).toBeInTheDocument();
  });

  it('сохраняет изменения через accountsApi.updateMe и обновляет store', async () => {
    vi.mocked(accountsApi.updateMe).mockResolvedValue(makeUser());
    renderWithProviders(<ProfileSection />);

    fireEvent.change(screen.getByLabelText('Фамилия'), { target: { value: 'Сидоров' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }));

    await waitFor(() => {
      expect(accountsApi.updateMe).toHaveBeenCalledWith({
        first_name: 'Иван',
        last_name: 'Сидоров',
        phone: '+998901234567',
        position: 'Менеджер',
        preferences: { language: 'ru', theme: 'light' },
      });
    });
    expect(toast.success).toHaveBeenCalledWith('Сохранено!');
    expect(useUserStore.getState().profile.lastName).toBe('Сидоров');
  });

  it('показывает ошибку и не трогает store при отказе API', async () => {
    vi.mocked(accountsApi.updateMe).mockRejectedValue(new Error('network'));
    renderWithProviders(<ProfileSection />);

    fireEvent.change(screen.getByLabelText('Фамилия'), { target: { value: 'Сидоров' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('Ошибка сохранения профиля');
    });
    expect(useUserStore.getState().profile.lastName).toBe('Петров');
  });
});
