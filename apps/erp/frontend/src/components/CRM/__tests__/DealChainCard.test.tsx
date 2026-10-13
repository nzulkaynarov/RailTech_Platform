import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import { DealChainCard } from '../DealChainCard';
import { crmApi, type DealDocumentHub } from '@/api/crmApi';
import { renderWithProviders } from '@/test/renderWithProviders';

// Хук useDealDocuments работает поверх этого мока — так проверяется реальная цепочка
// «ответ сервера → что увидел пользователь».
vi.mock('@/api/crmApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/crmApi')>();
  return {
    ...actual,
    crmApi: { ...actual.crmApi, getDealDocuments: vi.fn() },
  };
});

const getDealDocuments = vi.mocked(crmApi.getDealDocuments);

function makeHub(overrides: Partial<DealDocumentHub> = {}): DealDocumentHub {
  return {
    deal: 42,
    stage_code: 'CONTRACT_SIGNED',
    contract: {
      id: 7,
      number: 'CT-2026-00007',
      status: 'SIGNED',
      status_name: 'Подписан',
      total_amount: '112',
      client_signed_at: '2026-07-30T10:00:00Z',
      manager_signed_at: '2026-07-30T11:00:00Z',
      is_fully_signed: true,
      viewer_can_sign_client: false,
      viewer_can_sign_manager: false,
    },
    invoices: [],
    acts: [],
    fulfillment: null,
    payments_count: 0,
    payments_total: '0',
    viewer: { is_buyer_side: true, is_seller_side: false, is_viewer: false },
    next_step: null,
    ...overrides,
  };
}

describe('DealChainCard', () => {
  beforeEach(() => {
    getDealDocuments.mockReset();
    window.location.hash = '';
  });

  it('молчит, пока цепочки нет — вместо пяти пустых плиток', async () => {
    getDealDocuments.mockResolvedValue(
      makeHub({ contract: null, invoices: [], fulfillment: null }),
    );

    const { container } = renderWithProviders(<DealChainCard dealId={42} />);

    await waitFor(() => expect(getDealDocuments).toHaveBeenCalledWith(42));
    expect(container).toBeEmptyDOMElement();
  });

  it('показывает документы цепочки со статусами', async () => {
    getDealDocuments.mockResolvedValue(
      makeHub({
        invoices: [{
          id: 11,
          number: 'INV-2026-00011',
          status: 'ISSUED',
          status_name: 'Выставлен',
          total_incl_vat: '112',
          amount_paid: '0',
          balance_due: '112',
          due_date: '2026-08-13',
          issued_at: '2026-07-30',
        }],
      }),
    );

    renderWithProviders(<DealChainCard dealId={42} />);

    expect(await screen.findByText('Цепочка сделки')).toBeInTheDocument();
    expect(screen.getByText(/CT-2026-00007/)).toBeInTheDocument();
    expect(screen.getByText(/INV-2026-00011 · Выставлен/)).toBeInTheDocument();
  });

  it('шаг, адресованный зрителю, даёт кнопку действия', async () => {
    getDealDocuments.mockResolvedValue(
      makeHub({
        next_step: { code: 'PAY_INVOICE', for_viewer: true, page: 'invoices', object_id: 11 },
      }),
    );

    renderWithProviders(<DealChainCard dealId={42} />);

    expect(await screen.findByText('Счёт выставлен — можно оплачивать')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Открыть счёт' })).toBeInTheDocument();
  });

  it('шаг за контрагентом читается как ожидание и НЕ даёт кнопки', async () => {
    // Тот же код шага, что и выше: разница только в for_viewer с сервера. Это и есть замена
    // клиентской роли — продавцу не предлагают «оплатить» собственный счёт.
    getDealDocuments.mockResolvedValue(
      makeHub({
        viewer: { is_buyer_side: false, is_seller_side: true, is_viewer: false },
        next_step: { code: 'PAY_INVOICE', for_viewer: false, page: 'invoices', object_id: 11 },
      }),
    );

    renderWithProviders(<DealChainCard dealId={42} />);

    expect(await screen.findByText('Счёт выставлен — ждём оплату от клиента.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Открыть счёт' })).not.toBeInTheDocument();
  });

  it('клик по плитке ведёт точечно на документ, а не в общий реестр', async () => {
    getDealDocuments.mockResolvedValue(makeHub());

    renderWithProviders(<DealChainCard dealId={42} />);

    const tile = await screen.findByRole('button', { name: /Договор: CT-2026-00007/ });
    tile.click();

    await waitFor(() => expect(window.location.hash).toBe('#contracts?open=7'));
  });

  it('дошедшая до конца цепочка не предлагает следующий шаг', async () => {
    getDealDocuments.mockResolvedValue(
      makeHub({ next_step: { code: 'DONE', for_viewer: false, page: 'fulfillments', object_id: null } }),
    );

    renderWithProviders(<DealChainCard dealId={42} />);

    expect(
      await screen.findByText('Цепочка пройдена полностью: договор, оплата, акт и приёмка закрыты.'),
    ).toBeInTheDocument();
  });
});
