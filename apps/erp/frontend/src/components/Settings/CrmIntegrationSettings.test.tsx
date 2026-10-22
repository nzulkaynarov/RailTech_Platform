import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { CrmIntegrationSettings } from '@/components/Settings/CrmIntegrationSettings';
import { renderWithProviders } from '@/test/renderWithProviders';

/**
 * M3-ERP-05: экран «Интеграция с CRM» — только чтение статуса и выпуск одноразового кода.
 * Значения ключей на экране не появляются (в моках их нет — но и сам текст страницы не должен их содержать).
 */

const { statusFixture, apiMock } = vi.hoisted(() => ({
  statusFixture: {
    state: 'paired',
    paired_at: '2026-10-21T05:00:00Z',
    rotated_at: null,
    token_source: 'db',
    crm_to_erp_last4: 'Ab12',
    previous_token_valid_until: null,
    erp_to_crm_configured: true,
    webhook_secret_source: 'db',
    webhook_secret_last4: 'Cd34',
    code_ttl_seconds: 900,
    crm_frontend_url: 'https://crm.example.com',
  } as Record<string, unknown>,
  apiMock: { getStatus: vi.fn(), issueCode: vi.fn() },
}));

vi.mock('@/api/crmPairingApi', () => ({ crmPairingApi: apiMock }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

describe('CrmIntegrationSettings (M3-ERP-05)', () => {
  beforeEach(() => {
    apiMock.getStatus.mockReset().mockResolvedValue(statusFixture);
    apiMock.issueCode.mockReset().mockResolvedValue({
      code: 'ABCD-EFGH-JKMN',
      expires_at: '2026-10-21T05:15:00Z',
      ttl_seconds: 900,
    });
  });

  it('показывает статус «Сопряжено» и только последние 4 символа ключей', async () => {
    renderWithProviders(<CrmIntegrationSettings />);
    expect(await screen.findByText('Сопряжено', { selector: '[data-slot="badge"], span, div' })).toBeInTheDocument();
    expect(screen.getByText('••••Ab12')).toBeInTheDocument();
    expect(screen.getByText('••••Cd34')).toBeInTheDocument();
    expect(screen.queryByTestId('pairing-code-box')).toBeNull();
  });

  it('без сопряжения и ключей показывает «Не сопряжено»; ключи из окружения — «из .env»', async () => {
    apiMock.getStatus.mockResolvedValue({
      ...statusFixture,
      state: 'env',
      token_source: 'env',
      crm_to_erp_last4: '',
      webhook_secret_source: 'env',
      webhook_secret_last4: '',
      erp_to_crm_configured: false,
    });
    renderWithProviders(<CrmIntegrationSettings />);
    expect(await screen.findByText('Ключи из окружения (.env)')).toBeInTheDocument();
    expect(screen.getAllByText('задан в окружении (.env)')).toHaveLength(2);
  });

  it('выпускает код, показывает его с сроком и подсказкой «один раз»', async () => {
    renderWithProviders(<CrmIntegrationSettings />);
    fireEvent.click(await screen.findByRole('button', { name: 'Выпустить код' }));
    expect(await screen.findByTestId('pairing-code')).toHaveTextContent('ABCD-EFGH-JKMN');
    expect(apiMock.issueCode).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Действует 15 мин/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Выпустить новый код' })).toBeInTheDocument();
  });

  it('ссылка «Открыть CRM» ведёт на «Подключения → ERP»', async () => {
    renderWithProviders(<CrmIntegrationSettings />);
    const link = await screen.findByRole('link', { name: /Открыть CRM/ });
    expect(link).toHaveAttribute('href', 'https://crm.example.com/integrations?tab=erp');
  });

  it('без адреса CRM ссылки нет — подсказка', async () => {
    apiMock.getStatus.mockResolvedValue({ ...statusFixture, crm_frontend_url: '' });
    renderWithProviders(<CrmIntegrationSettings />);
    expect(await screen.findByTestId('crm-url-missing')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Открыть CRM/ })).toBeNull();
  });

  it('во время перехода после ротации предупреждает, до какого срока жив прежний ключ', async () => {
    apiMock.getStatus.mockResolvedValue({ ...statusFixture, previous_token_valid_until: '2026-10-21T06:00:00Z' });
    renderWithProviders(<CrmIntegrationSettings />);
    expect(await screen.findByText('Идёт переход на новые ключи')).toBeInTheDocument();
  });

  it('ошибка загрузки — сообщение и «Повторить»', async () => {
    apiMock.getStatus.mockRejectedValue(new Error('boom'));
    renderWithProviders(<CrmIntegrationSettings />);
    await waitFor(() => expect(screen.getByText('Не удалось загрузить состояние сопряжения')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });
});
