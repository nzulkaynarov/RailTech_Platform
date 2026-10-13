import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';

import { SecuritySection } from '@/components/Settings/SecuritySection';
import { accountsApi, type Session } from '@/api/accountsApi';
import { useUserStore } from '@/store/userStore';
import { renderWithProviders } from '@/test/renderWithProviders';

// Мокаем слой API-клиента (не сеть): смена пароля, 2FA и сессии бьют в эти mock'и.
vi.mock('@/api/accountsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/accountsApi')>();
  return {
    ...actual,
    accountsApi: {
      ...actual.accountsApi,
      changePassword: vi.fn(),
      getActiveSessions: vi.fn(),
      revokeAllSessions: vi.fn(),
      setup2FA: vi.fn(),
      verify2FA: vi.fn(),
      disable2FA: vi.fn(),
    },
  };
});

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const SESSIONS: Session[] = [
  { id: 1, created_at: '2026-07-01T10:00:00Z', expires_at: '2026-07-08T10:00:00Z', is_current: true },
];

describe('SecuritySection', () => {
  beforeEach(() => {
    vi.mocked(accountsApi.changePassword).mockReset();
    vi.mocked(accountsApi.setup2FA).mockReset();
    vi.mocked(accountsApi.verify2FA).mockReset();
    vi.mocked(accountsApi.disable2FA).mockReset();
    vi.mocked(accountsApi.getActiveSessions).mockReset().mockResolvedValue([...SESSIONS]);
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
    useUserStore.setState((state) => ({ profile: { ...state.profile, is_2fa_enabled: false } }));
  });

  it('рендерит карточки пароля, 2FA и сессии full width', async () => {
    renderWithProviders(<SecuritySection />);

    // Левая колонка (§2.4) — заголовок и описание секции из НОВЫХ ключей.
    expect(screen.getByRole('heading', { name: 'Безопасность' })).toBeInTheDocument();
    expect(
      screen.getByText('Пароль, двухфакторная аутентификация и активные сессии аккаунта'),
    ).toBeInTheDocument();

    // Карточка пароля + карточка 2FA (флоу не менялся — кнопка setup на месте).
    expect(screen.getByText('Пароль')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Изменить' })).toBeInTheDocument();
    expect(screen.getByText('Двухфакторная аутентификация')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Включить 2FA' })).toBeInTheDocument();

    // Сессии подгружаются из API; текущая помечена бейджем.
    expect(await screen.findByText('Активные сессии')).toBeInTheDocument();
    expect(screen.getByText('Текущая')).toBeInTheDocument();
    expect(accountsApi.getActiveSessions).toHaveBeenCalledTimes(1);
  });

  it('не отправляет запрос при несовпадении паролей', async () => {
    renderWithProviders(<SecuritySection />);

    fireEvent.click(screen.getByRole('button', { name: 'Изменить' }));
    expect(await screen.findByText('Изменить пароль')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Текущий пароль'), { target: { value: 'old-pass' } });
    fireEvent.change(screen.getByLabelText('Новый пароль'), { target: { value: 'new-pass-1' } });
    fireEvent.change(screen.getByLabelText('Подтвердите пароль'), { target: { value: 'other' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('Пароли не совпадают');
    });
    expect(accountsApi.changePassword).not.toHaveBeenCalled();
  });

  it('меняет пароль через accountsApi.changePassword и закрывает диалог', async () => {
    vi.mocked(accountsApi.changePassword).mockResolvedValue({ message: 'ok' });
    renderWithProviders(<SecuritySection />);

    fireEvent.click(screen.getByRole('button', { name: 'Изменить' }));
    expect(await screen.findByText('Изменить пароль')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Текущий пароль'), { target: { value: 'old-pass' } });
    fireEvent.change(screen.getByLabelText('Новый пароль'), { target: { value: 'new-pass-1' } });
    fireEvent.change(screen.getByLabelText('Подтвердите пароль'), { target: { value: 'new-pass-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => {
      expect(accountsApi.changePassword).toHaveBeenCalledWith({
        current_password: 'old-pass',
        new_password: 'new-pass-1',
      });
    });
    expect(toast.success).toHaveBeenCalledWith('Пароль успешно изменён');
    await waitFor(() => {
      expect(screen.queryByText('Изменить пароль')).not.toBeInTheDocument();
    });
  });

  it('2FA setup→verify: показывает QR и подтверждает код + пароль (step-up)', async () => {
    vi.mocked(accountsApi.setup2FA).mockResolvedValue({ secret: 'SECRET123', uri: 'otpauth://totp/test' });
    vi.mocked(accountsApi.verify2FA).mockResolvedValue({ detail: 'OK' });
    renderWithProviders(<SecuritySection />);

    fireEvent.click(screen.getByRole('button', { name: 'Включить 2FA' }));
    // После setup — поле пароля (step-up) + поле кода (QR рендерится рядом) и кнопка подтверждения.
    const codeInput = await screen.findByPlaceholderText('000000');
    fireEvent.change(screen.getByLabelText('Подтвердите текущим паролем'), { target: { value: 'my-pass' } });
    fireEvent.change(codeInput, { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить' }));

    await waitFor(() => {
      expect(accountsApi.verify2FA).toHaveBeenCalledWith({
        secret: 'SECRET123',
        code: '123456',
        current_password: 'my-pass',
      });
    });
    expect(useUserStore.getState().profile.is_2fa_enabled).toBe(true);
  });

  it('2FA disable: требует пароль и код (step-up)', async () => {
    vi.mocked(accountsApi.disable2FA).mockResolvedValue({ detail: 'OK' });
    useUserStore.setState((state) => ({ profile: { ...state.profile, is_2fa_enabled: true } }));
    renderWithProviders(<SecuritySection />);

    fireEvent.change(screen.getByLabelText('Подтвердите текущим паролем'), { target: { value: 'my-pass' } });
    fireEvent.change(screen.getByPlaceholderText('000000'), { target: { value: '654321' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отключить' }));

    await waitFor(() => {
      expect(accountsApi.disable2FA).toHaveBeenCalledWith({ code: '654321', current_password: 'my-pass' });
    });
    expect(useUserStore.getState().profile.is_2fa_enabled).toBe(false);
  });
});
