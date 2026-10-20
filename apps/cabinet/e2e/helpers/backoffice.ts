import { expect } from '@playwright/test';
import type { ErpApi } from './erp';

/**
 * Шаги бэк-офиса BUSINESS §4 (4–9) — подготовка данных для клиента: сотрудник FIX-51 штатно ведёт заявку
 * в ERP через те же методы API, что и ERP SPA. Это не прогон M1 (его делает FIX-50), а то, что клиент потом видит в Cabinet.
 */
export interface QuoteLine {
  product: number;
  quantity: number;
  price: string; // цена закупки/базовая, UZS; маржа 25 % сверху
}

export async function pickProducts(erp: ErpApi, names: string[]): Promise<number[]> {
  const { json } = await erp.ok('GET', 'catalog/products/?page_size=100');
  const rows = json.results as { id: number; name: string }[];
  return names.map((name) => {
    const found = rows.find((p) => p.name.includes(name));
    expect(found, `товар «${name}» есть в каталоге ERP`).toBeTruthy();
    return found!.id;
  });
}

async function approveAllAndSend(erp: ErpApi, quoteId: number): Promise<void> {
  await erp.ok('POST', `crm/quotes/${quoteId}/submit-for-review/`);
  for (let round = 0; round < 4; round += 1) {
    const { json } = await erp.ok('GET', `crm/quotes/${quoteId}/`);
    if (json.status_code === 'READY_TO_SEND') break;
    const steps = (json.approval_steps as { id: number; status: string; can_act: boolean }[]).filter((s) => s.status === 'PENDING' && s.can_act);
    expect(steps.length, 'есть шаг согласования, который сотрудник FIX-51 может выполнить').toBeGreaterThan(0);
    for (const step of steps) {
      await erp.ok('POST', `crm/quotes/${quoteId}/approval-act/`, { step_id: step.id, decision: 'APPROVE', comment: 'FIX-51: подготовка данных прогона' });
    }
  }
  await erp.ok('POST', `crm/quotes/${quoteId}/send-to-client/`, {});
}

/** Заявка → расчёт → КП со строками → согласование → отправка клиенту. Возвращает id КП. */
export async function buildAndSendQuote(erp: ErpApi, dealId: number, lines: QuoteLine[]): Promise<number> {
  await erp.ok('POST', `crm/deals/${dealId}/claim/`);
  await erp.ok('POST', `crm/deals/${dealId}/change-stage/`, { stage_code: 'SOURCING' });
  await erp.ok('POST', `crm/deals/${dealId}/change-stage/`, { stage_code: 'CALCULATING' });
  const quote = await erp.ok('POST', 'crm/quotes/', { deal: dealId });
  const quoteId = quote.json.id as number;
  for (const line of lines) {
    const item = await erp.ok('POST', 'crm/quote-items/', { quote: quoteId, product: line.product, quantity: line.quantity, margin_percent: '25.00' });
    await erp.ok('PATCH', `crm/quote-items/${item.json.id}/`, { frozen_base_price: line.price, frozen_currency: 'UZS', lead_time_days: 14, unit: 'шт' });
  }
  await erp.ok('PATCH', `crm/quotes/${quoteId}/`, { delivery_lead_time_days: 14 });
  await approveAllAndSend(erp, quoteId);
  return quoteId;
}

/** Новая версия КП после отказа клиента (копия строк) → согласование → отправка. Возвращает id новой версии. */
export async function resendQuoteVersion(erp: ErpApi, quoteId: number): Promise<number> {
  const copy = await erp.ok('POST', `crm/quotes/${quoteId}/duplicate/`, {});
  const next = copy.json.id as number;
  await approveAllAndSend(erp, next);
  return next;
}

async function waitFor<T>(what: string, read: () => Promise<T | null>, timeoutMs = 45_000): Promise<T> {
  const until = Date.now() + timeoutMs;
  for (;;) {
    const value = await read();
    if (value !== null) return value;
    if (Date.now() > until) throw new Error(`не дождались: ${what}`);
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

export async function contractIdByDeal(erp: ErpApi, dealId: number): Promise<number> {
  return waitFor('договор по сделке', async () => {
    const { json } = await erp.ok('GET', 'crm/contracts/?page_size=100');
    const found = (json.results as { id: number; deal: number }[]).find((c) => c.deal === dealId);
    return found ? found.id : null;
  });
}

/** Подпись исполнителя; затем Celery создаёт черновик счёта и отгрузку — ждём их, потом выставляем счёт. Возвращает id счёта. */
export async function signAndInvoice(erp: ErpApi, dealId: number, contractId: number): Promise<number> {
  await erp.ok('POST', `crm/contracts/${contractId}/sign-manager/`);
  const invoiceId = await waitFor('счёт-черновик по договору', async () => {
    const { json } = await erp.ok('GET', `crm/invoices/?deal=${dealId}`);
    const found = (json.results as { id: number }[])[0];
    return found ? found.id : null;
  }).catch(async () => (await erp.ok('POST', 'crm/invoices/generate-from-contract/', { contract_id: contractId, due_days: 14 })).json.id as number);
  await waitFor('отгрузка по сделке', async () => {
    const { json } = await erp.ok('GET', `crm/fulfillments/?deal=${dealId}`);
    return (json.results as unknown[]).length ? true : null;
  });
  await erp.ok('POST', `crm/invoices/${invoiceId}/issue/`);
  return invoiceId;
}

export async function recordPayment(erp: ErpApi, invoiceId: number, amount: string): Promise<void> {
  await erp.ok('POST', `crm/invoices/${invoiceId}/record-payment/`, { amount, paid_at: new Date().toISOString().slice(0, 10), method: 'BANK_TRANSFER', reference: 'FIX-51 аванс' });
}

export async function shipAndDeliver(erp: ErpApi, dealId: number, step: 'SHIPPED' | 'DELIVERED'): Promise<void> {
  const extra = step === 'SHIPPED' ? { tracking_number: 'FIX51-TRK-001', carrier: 'FIX-51 Логистика', expected_delivery_date: '2026-11-05' } : {};
  await erp.ok('POST', 'crm/fulfillments/update-status/', { deal_id: dealId, status: step, ...extra });
}

export async function issueAct(erp: ErpApi, invoiceId: number): Promise<number> {
  const act = await erp.ok('POST', `crm/invoices/${invoiceId}/generate-act/`);
  return act.json.id as number;
}
