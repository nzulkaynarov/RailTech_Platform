import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';

import { PostContractStrip } from '../DashboardWidgets';
import { invoicesApi, actsApi, type Invoice, type Act } from '@/api/billingApi';
import { fulfillmentApi, type Fulfillment } from '@/api/fulfillmentApi';
import { renderWithProviders } from '@/test/renderWithProviders';

/**
 * F3 — вторая половина воронки на дашборде. Полоса внимания заканчивалась на «Договорах на
 * подписи»: счета, акты и поставки на дашборд не попадали вовсе.
 */

vi.mock('@/api/billingApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/billingApi')>();
  return {
    ...actual,
    invoicesApi: { ...actual.invoicesApi, list: vi.fn() },
    actsApi: { ...actual.actsApi, list: vi.fn() },
  };
});

vi.mock('@/api/fulfillmentApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/fulfillmentApi')>();
  return {
    ...actual,
    fulfillmentApi: { ...actual.fulfillmentApi, list: vi.fn() },
  };
});

const listInvoices = vi.mocked(invoicesApi.list);
const listActs = vi.mocked(actsApi.list);
const listFulfillments = vi.mocked(fulfillmentApi.list);

function makeInvoice(id: number, status: Invoice['status'], dueDate: string | null): Invoice {
  return {
    id,
    deal: id,
    contract: null,
    number: `INV-${id}`,
    status,
    issued_at: '2026-07-01',
    due_date: dueDate,
    subtotal_excl_vat: '100',
    vat_amount: '12',
    total_incl_vat: '112',
    amount_paid: '0',
    balance_due: '112',
    currency: null,
    pdf_file: null,
    pdf_url: null,
    notes: '',
    items: [],
    payments: [],
    viewer_can_manage: true,
    created_at: '2026-07-01T10:00:00Z',
    updated_at: '2026-07-01T10:00:00Z',
  };
}

function makeFulfillment(id: number, status: Fulfillment['status']): Fulfillment {
  return {
    id,
    deal: id,
    contract: null,
    status,
    shipped_at: null,
    delivered_at: null,
    accepted_at: null,
    expected_delivery_date: null,
    tracking_number: '',
    carrier: '',
    viewer_can_ship: true,
    notes: '',
    created_at: '2026-07-01T10:00:00Z',
    updated_at: '2026-07-01T10:00:00Z',
  };
}

function makeAct(id: number): Act {
  return {
    id,
    deal: id,
    contract: null,
    invoice: id,
    number: `ACT-${id}`,
    status: 'ISSUED',
    issued_at: '2026-07-01',
    signed_at: null,
    total_amount: '112',
    pdf_file: null,
    pdf_url: null,
    signed_file: null,
    signed_file_url: null,
    viewer_can_remind: false,
    viewer_can_cancel: false,
    viewer_can_reissue: false,
    cancellation_reason: '',
    reminder_sent_at: null,
    issuer_signer: null,
    issuer_signer_name: null,
    issuer_signed_at: null,
    acceptor_signer: null,
    acceptor_signer_name: null,
    acceptor_signed_at: null,
    rejection_reason: '',
    notes: '',
    created_at: '2026-07-01T10:00:00Z',
    updated_at: '2026-07-01T10:00:00Z',
  };
}

/** Плитка, владеющая подписью. */
async function findTile(label: string): Promise<HTMLElement> {
  const labelNode = await screen.findByText(label);
  const tile = labelNode.closest('button');
  if (!tile) throw new Error(`нет плитки для «${label}»`);
  return tile;
}

describe('PostContractStrip', () => {
  beforeEach(() => {
    listInvoices.mockReset();
    listActs.mockReset();
    listFulfillments.mockReset();
  });

  it('молчит целиком, пока сделки не дошли до денег', async () => {
    listInvoices.mockResolvedValue([]);
    listActs.mockResolvedValue([]);
    listFulfillments.mockResolvedValue([]);

    const { container } = renderWithProviders(<PostContractStrip onNavigate={vi.fn()} />);

    // Блок исчезает только когда данные ПРИЕХАЛИ и все нули; до этого висит скелет.
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it('при сбое загрузки показывает ошибку с повтором, а не пустоту', async () => {
    // Ноль обязан означать ноль: «Счета к оплате: 0» при недоступном API — ложь, по которой
    // принимают решения (аудит UI, U2).
    listInvoices.mockRejectedValue(new Error('boom'));
    listActs.mockRejectedValue(new Error('boom'));
    listFulfillments.mockRejectedValue(new Error('boom'));

    renderWithProviders(<PostContractStrip onNavigate={vi.fn()} />);

    expect(await screen.findByText('Не удалось загрузить данные')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });

  it('бэк-офису показывает счета к выставлению, ожидание оплаты, акты и поставки', async () => {
    listInvoices.mockResolvedValue([
      makeInvoice(1, 'DRAFT', null),
      makeInvoice(2, 'ISSUED', '2026-12-31'),
      makeInvoice(3, 'PARTIAL', '2026-12-31'),
      makeInvoice(4, 'PAID', null),
    ]);
    listActs.mockResolvedValue([makeAct(9)]);
    listFulfillments.mockResolvedValue([makeFulfillment(5, 'SHIPPED'), makeFulfillment(6, 'ACCEPTED')]);

    renderWithProviders(<PostContractStrip onNavigate={vi.fn()} />);

    expect(within(await findTile('Счета к выставлению')).getByText('1')).toBeInTheDocument();
    // ISSUED + PARTIAL ждут денег; PAID уже нет.
    expect(within(await findTile('Ждут оплаты')).getByText('2')).toBeInTheDocument();
    // Акт выпустил бэк-офис, принимает клиент — плитка считает, сколько висит на нём.
    expect(within(await findTile('Акты ждут приёмки')).getByText('1')).toBeInTheDocument();
    // ACCEPTED — уже не «в пути».
    expect(within(await findTile('Поставки в пути')).getByText('1')).toBeInTheDocument();
  });

  it('просрочку считает по сроку оплаты, а не по статусу OVERDUE (его никто не проставляет)', async () => {
    listInvoices.mockResolvedValue([
      makeInvoice(1, 'ISSUED', '2020-01-01'),
      makeInvoice(2, 'ISSUED', '2999-01-01'),
    ]);
    listActs.mockResolvedValue([]);
    listFulfillments.mockResolvedValue([]);

    renderWithProviders(<PostContractStrip onNavigate={vi.fn()} />);

    const tile = await findTile('Ждут оплаты');
    expect(within(tile).getByText('2')).toBeInTheDocument();
    expect(within(tile).getByText('1 просрочен')).toBeInTheDocument();
  });

  it('клик по плитке ведёт на её страницу', async () => {
    const onNavigate = vi.fn();
    listInvoices.mockResolvedValue([makeInvoice(1, 'DRAFT', null)]);
    listActs.mockResolvedValue([]);
    listFulfillments.mockResolvedValue([]);

    renderWithProviders(<PostContractStrip onNavigate={onNavigate} />);

    (await findTile('Счета к выставлению')).click();
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith('invoices'));
  });
});
