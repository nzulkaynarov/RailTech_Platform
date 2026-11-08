import type { TFunction } from 'i18next';

import type { PortalNotification } from '@/api/portal';
import { formatDate, formatMoney } from '@/lib/format';

/**
 * Текст уведомления колокольчика (NOTIFY-2): ERP присылает объект, действие, ключ текста и параметры, текст на языке
 * контакта собирает Cabinet — `notifications.text.<text_key>`. Незнакомый ключ (новый вид в ERP раньше Cabinet) — общий
 * текст с номером объекта, а не пустая строка.
 */
const KNOWN_TEXTS = new Set([
  'quote_sent',
  'invoice_issued',
  'payment_overdue',
  'act_issued',
  'delivery_status_changed',
  'delivery_eta_changed',
  'manager_replied',
  'partner_card_returned',
  'partner_card_published',
  'partner_order_sent',
  'partner_rfq_sent',
  'partner_goods_received',
]);

/** Статусы поставки в параметре `status` (`DeliveryEvent.status` ERP) — подписи из `status.delivery.*`. */
const DELIVERY_STATUSES = new Set(['assembling', 'in_transit', 'ready_to_ship', 'shipped', 'delivered']);

export function notificationText(item: PortalNotification, t: TFunction): string {
  const p = item.params;
  const values = {
    number: p.number ?? item.object.number ?? '',
    deal: p.deal ?? '',
    amount: p.amount && p.currency ? formatMoney({ amount: p.amount, currency: p.currency }) : '',
    due: p.due_date ? formatDate(p.due_date) : '',
    eta: p.eta ? formatDate(p.eta) : '',
    status: p.status && DELIVERY_STATUSES.has(p.status) ? t(`status.delivery.${p.status}`) : (p.status ?? ''),
  };
  if (!KNOWN_TEXTS.has(item.text_key)) return t('notifications.text.fallback', values);
  const key = item.text_key === 'act_issued' && p.reminder ? 'act_issued_reminder' : item.text_key;
  return t(`notifications.text.${key}`, values);
}

/** Ссылка ERP — путь кабинета от корня; чужое (не `/…`, протокол, `//хост`) не открываем — ведём в профиль. */
export function safeNotificationLink(link: string): string {
  return /^\/(?!\/)/.test(link) ? link : '/profile';
}
