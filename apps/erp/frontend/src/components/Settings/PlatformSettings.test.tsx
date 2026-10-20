import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { PlatformSettings } from '@/components/Settings/PlatformSettings';
import { renderWithProviders } from '@/test/renderWithProviders';

/**
 * Spec PR 5 (вариант Б): мёртвые переключатели maintenance_mode / is_two_factor_required
 * убраны из UI PlatformSettings; поля БД зарезервированы. Тест фиксирует, что:
 *  1) в секции нет ни одного Switch и старых подписей;
 *  2) сохранение шлёт payload БЕЗ обоих полей, даже если бэкенд их вернул.
 */

// Данные и мутация хука мокаются (не сеть): фикстура НАМЕРЕННО содержит оба
// зарезервированных поля — компонент обязан их игнорировать.
const { settingsFixture, mutateAsyncMock } = vi.hoisted(() => ({
  settingsFixture: {
    vat_rate: '12.00',
    standard_margin: '15.00',
    exchange_rate_usd_uzs: '12650.0000',
    platform_name: 'ERP Platform',
    support_email: 'support@example.com',
    logo_url: 'https://example.com/logo.png',
    domain: 'erp.example.com',
    maintenance_mode: true,
    is_two_factor_required: true,
    updated_at: '2026-07-10T10:00:00Z',
  },
  mutateAsyncMock: vi.fn(),
}));

vi.mock('@/hooks/useSystemSettings', () => ({
  useSystemSettings: () => ({ data: settingsFixture, isLoading: false }),
  useUpdateSystemSettings: () => ({ mutateAsync: mutateAsyncMock, isPending: false }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe('PlatformSettings (spec PR 5, вариант Б)', () => {
  beforeEach(() => {
    mutateAsyncMock.mockReset().mockResolvedValue(settingsFixture);
  });

  it('рендерит живые поля без переключателей maintenance/2FA', () => {
    renderWithProviders(<PlatformSettings />);

    // Живые настройки на месте (значения из данных бэкенда).
    expect(screen.getByText('Системные настройки')).toBeInTheDocument();
    expect(screen.getByDisplayValue('12.00')).toBeInTheDocument();
    expect(screen.getByDisplayValue('12.00')).not.toBeDisabled();
    // Второго ручного курса нет (FIX-41): курс — только из справочника ЦБ, формы курса в настройках нет.
    expect(screen.queryByDisplayValue('12650.0000')).not.toBeInTheDocument();
    expect(screen.queryByText('Курс USD→UZS')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('ERP Platform')).toBeInTheDocument();
    expect(screen.getByDisplayValue('ERP Platform')).toBeDisabled();
    expect(screen.getByDisplayValue('support@example.com')).toBeInTheDocument();
    expect(screen.getByDisplayValue('support@example.com')).toBeDisabled();
    expect(screen.getByDisplayValue('https://example.com/logo.png')).toBeInTheDocument();
    expect(screen.getByDisplayValue('https://example.com/logo.png')).toBeDisabled();
    expect(screen.getByDisplayValue('erp.example.com')).toBeInTheDocument();
    expect(screen.getByDisplayValue('erp.example.com')).toBeDisabled();

    // standard_margin убран из UI (P9): поле инертно, не показываем и не редактируем.
    expect(screen.queryByDisplayValue('15.00')).not.toBeInTheDocument();

    // Мёртвые переключатели удалены: ни одного Switch и ни одной старой подписи.
    expect(screen.queryAllByRole('switch')).toHaveLength(0);
    expect(screen.queryByText('Режим обслуживания')).not.toBeInTheDocument();
    expect(screen.queryByText('Обязательная 2FA')).not.toBeInTheDocument();
  });

  it('сохранение шлёт payload без maintenance_mode и is_two_factor_required', async () => {
    renderWithProviders(<PlatformSettings />);

    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => {
      expect(mutateAsyncMock).toHaveBeenCalledTimes(1);
    });
    expect(mutateAsyncMock).toHaveBeenCalledWith({
      vat_rate: '12.00',
      platform_name: 'ERP Platform',
      support_email: 'support@example.com',
      logo_url: 'https://example.com/logo.png',
      domain: 'erp.example.com',
    });
    const payload = mutateAsyncMock.mock.calls[0][0];
    expect(payload).not.toHaveProperty('maintenance_mode');
    expect(payload).not.toHaveProperty('is_two_factor_required');
    // standard_margin более не отправляется (P9).
    expect(payload).not.toHaveProperty('standard_margin');
    // Курс не отправляется: бэкенд отдаёт его только на чтение (FIX-41).
    expect(payload).not.toHaveProperty('exchange_rate_usd_uzs');
  });
});
