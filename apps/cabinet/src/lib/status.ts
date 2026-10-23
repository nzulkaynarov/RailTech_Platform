import type { Schemas } from '@/api/portal';

/**
 * Статусы из контракта → подпись (`status.<entity>.<code>` в словарях) и тон бейджа (семантический
 * токен: success / warning / danger / info / neutral). Код сравнивается как есть, показывается подпись
 * (CONVENTIONS.md §5). Тон отвечает на вопрос клиента «нужно ли что-то от меня»: warning — ждём его решения.
 */
export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

type StatusMaps = {
  request: Schemas['RequestStatus'];
  quote: Schemas['QuoteStatus'];
  contract: Schemas['ContractStatus'];
  invoice: Schemas['InvoiceStatus'];
  act: Schemas['ActStatus'];
  delivery: Schemas['DeliveryStatus'];
  availability: Schemas['Availability'];
};

export type StatusEntity = keyof StatusMaps;

const TONES: { [E in StatusEntity]: Record<StatusMaps[E], StatusTone> } = {
  request: { new: 'info', in_progress: 'info', quoted: 'warning', closed: 'neutral' },
  quote: { sent: 'warning', viewed: 'warning', accepted: 'success', rejected: 'danger', expired: 'neutral' },
  contract: {
    sent: 'warning',
    signed_by_client: 'info',
    signed_by_company: 'warning',
    signed: 'success',
    cancelled: 'neutral',
  },
  invoice: { issued: 'info', partially_paid: 'warning', paid: 'success', overdue: 'danger', cancelled: 'neutral' },
  act: { issued: 'warning', accepted: 'success', returned: 'danger' },
  delivery: {
    assembling: 'neutral',
    in_transit: 'info',
    ready_to_ship: 'info',
    shipped: 'info',
    delivered: 'success',
    accepted: 'success',
    disputed: 'danger',
  },
  availability: { in_stock: 'success', on_order: 'warning', expected: 'info' },
};

export function statusTone<E extends StatusEntity>(entity: E, code: StatusMaps[E]): StatusTone {
  return (TONES[entity] as Record<string, StatusTone>)[code] ?? 'neutral';
}

/** Ключ подписи статуса; полнота ключей во всех словарях проверяется тестом `status.test.ts`. */
export function statusLabelKey<E extends StatusEntity>(entity: E, code: StatusMaps[E]): string {
  return `status.${entity}.${code}`;
}

/** Все коды сущности — для тестов полноты словарей и фильтров. */
export function statusCodes<E extends StatusEntity>(entity: E): StatusMaps[E][] {
  return Object.keys(TONES[entity]) as StatusMaps[E][];
}

export const STATUS_ENTITIES = Object.keys(TONES) as StatusEntity[];

/** Действует ли ещё КП: решение клиента возможно только в статусах «отправлено / просмотрено». */
export function isQuoteOpen(status: Schemas['QuoteStatus']): boolean {
  return status === 'sent' || status === 'viewed';
}

/** Договор ждёт подписи клиента. */
export function contractAwaitsClient(status: Schemas['ContractStatus']): boolean {
  return status === 'sent' || status === 'signed_by_company';
}
