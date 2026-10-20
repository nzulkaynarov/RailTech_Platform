import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { CompanyDefaultsSettings } from '@/components/Cabinet/CompanyDefaultsSettings';
import { accountsApi } from '@/api/accountsApi';

/**
 * FIX-42 (F-6): флаг «Уведомлять клиента о сдвигах сроков» никто на бэкенде не читал — переключатель
 * убран из «Дефолтов КП», запрос сохранения его не шлёт (уведомление о сдвиге срока идёт из CRM по событию).
 */

vi.mock('@/hooks/useCapabilities', () => ({ useHasCompanyPermission: () => true }));
vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (s: { user: { company: { id: number } } }) => unknown) =>
    selector({ user: { company: { id: 7 } } }),
}));
vi.mock('@/hooks/useMasterData', () => ({
  useCurrencies: () => ({ data: [] }),
  useDeliveryBases: () => ({ data: [] }),
}));
vi.mock('@/api/accountsApi', () => ({
  accountsApi: { getCompanySettings: vi.fn(), updateCompanySettings: vi.fn() },
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

describe('CompanyDefaultsSettings: неработающего флага уведомлений нет', () => {
  beforeEach(() => {
    vi.mocked(accountsApi.getCompanySettings).mockReset().mockResolvedValue({
      id: 1,
      company: 7,
      default_vat_rate: '12.00',
      fx_rate_max_age_days: 7,
      notify_client_on_schedule_shift: true,
    } as never);
    vi.mocked(accountsApi.updateCompanySettings).mockReset().mockResolvedValue({} as never);
  });

  it('нет переключателя и подписи, сохранение не шлёт notify_client_on_schedule_shift', async () => {
    renderWithProviders(<CompanyDefaultsSettings />);

    await screen.findByText('Дефолты КП');
    expect(screen.queryByText(/Уведомлять клиента о сдвигах/)).not.toBeInTheDocument();
    expect(screen.queryAllByRole('switch')).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(accountsApi.updateCompanySettings).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(accountsApi.updateCompanySettings).mock.calls[0][1];
    expect(payload).not.toHaveProperty('notify_client_on_schedule_shift');
  });
});
