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
