import type { Invoice, Money } from '@/api/portal';
import { businessToday, daysBetween, subtractMoney } from './format';

/**
 * Счёт глазами клиента: остаток к оплате и просрочка. Просрочка вычисляется из `due_date` по
 * календарю Ташкента, а не только из статуса ERP: статус `overdue` ставит ночная задача ERP, а
 * клиент должен увидеть просрочку в тот же день (B2B InvoicesPage подсвечивал так же).
 */
export interface InvoiceView {
  remaining: Money | null;
  /** Дней просрочки (> 0) или `null`, если счёт не просрочен. */
  overdueDays: number | null;
  /** Статус для показа: `overdue` при вычисленной просрочке, иначе статус ERP. */
  displayStatus: Invoice['status'];
}

const CLOSED: ReadonlyArray<Invoice['status']> = ['paid', 'cancelled'];

export function invoiceView(invoice: Invoice, now: number): InvoiceView {
  const remaining = subtractMoney(invoice.total, invoice.paid);
  if (CLOSED.includes(invoice.status)) return { remaining, overdueDays: null, displayStatus: invoice.status };
  const days = daysBetween(invoice.due_date, businessToday(now));
  const unpaid = remaining === null || !/^0+\.00$/.test(remaining.amount);
  const overdue = unpaid && (days > 0 || invoice.status === 'overdue');
  return {
    remaining,
    overdueDays: overdue ? Math.max(days, 1) : null,
    displayStatus: overdue ? 'overdue' : invoice.status,
  };
}

export function invoiceViews(invoices: Invoice[], now: number = Date.now()): Map<number, InvoiceView> {
  const map = new Map<number, InvoiceView>();
  for (const inv of invoices) {
    map.set(inv.id, invoiceView(inv, now));
  }
  return map;
}

/** Счёт ещё ждёт денег — к нему можно приложить платёжку (оплаченный и отменённый ERP отклонит: `INVOICE_NOT_OPEN`). */
export function invoiceOpen(invoice: Pick<Invoice, 'status'>): boolean {
  return !CLOSED.includes(invoice.status);
}

/** Комментарий к платёжке — до 500 знаков (`PaymentProofCreate.comment`). */
export const PROOF_COMMENT_MAX = 500;

/**
 * Сумма платежа из поля ввода → `Amount` контракта (`"1500000.00"`): пробелы разрядов убираются, запятая — десятичный
 * знак. Пусто — `null` (сумма необязательна); не число, ноль или больше двух знаков после точки — `'invalid'`.
 */
export function parseAmount(text: string): string | null | 'invalid' {
  const clean = text.replace(/[\s\u00a0\u202f]/g, '').replace(',', '.');
  if (!clean) return null;
  const match = /^(\d{1,12})(?:\.(\d{1,2}))?$/.exec(clean);
  if (!match) return 'invalid';
  const value = `${BigInt(match[1])}.${(match[2] ?? '').padEnd(2, '0')}`;
  return /^0\.00$/.test(value) ? 'invalid' : value;
}
