import type { DealRef, MessageContext, MessageContextKind, PortalMessage } from '@/api/portal';

/**
 * Чат кабинета (CHAT-1, ADR-0023): чистые функции экрана «Сообщения» — ссылка «Написать менеджеру» с меткой документа,
 * разбор метки из адреса, ключ повтора сообщения, слияние ленты при опросе.
 */

/** Опрос ленты, пока экран открыт и вкладка видима (SSE — после пилота, ADR-0023). */
export const POLL_INTERVAL_MS = 10_000;
/** Лимит текста сообщения — как в контракте (`PortalMessageCreate.text`). */
export const MESSAGE_MAX_LENGTH = 4000;
/** Страниц «догнать ленту» за один опрос не больше — защита от бесконечного цикла при сбое сервера. */
export const MAX_CATCH_UP_PAGES = 5;

const KINDS: readonly MessageContextKind[] = ['deal', 'quote', 'invoice', 'act'];

/** Адрес чата; с меткой — `?about=<вид>&id=<id>&number=<номер>` («Написать менеджеру» со страницы документа). */
export function chatLink(context?: MessageContext | null): string {
  if (!context) return '/messages';
  const search = new URLSearchParams({ about: context.kind, id: String(context.id), number: context.number });
  return `/messages?${search.toString()}`;
}

/** Метка сделки документа (строка договора): нет сделки — общее сообщение без метки. */
export function dealContext(deal: DealRef | null | undefined): MessageContext | null {
  return deal ? { kind: 'deal', id: deal.id, number: deal.number } : null;
}

/** Метка документа из адреса чата; неполная или чужого вида — без метки. */
export function contextFromSearch(search: URLSearchParams): MessageContext | null {
  const kind = search.get('about');
  const id = Number(search.get('id'));
  const number = search.get('number')?.trim() ?? '';
  if (!kind || !(KINDS as readonly string[]).includes(kind)) return null;
  if (!Number.isInteger(id) || id <= 0 || !number) return null;
  return { kind: kind as MessageContextKind, id, number: number.slice(0, 64) };
}

/** Куда ведёт метка документа в ленте: сделка и КП — карточка, счёт и акт — их список. */
export function contextHref(context: MessageContext): string {
  switch (context.kind) {
    case 'deal':
      return `/deals/${context.id}`;
    case 'quote':
      return `/quotes/${context.id}`;
    case 'invoice':
      return '/invoices';
    case 'act':
      return '/acts';
  }
}

/** Ключ повтора сообщения (контракт: `^[A-Za-z0-9_-]{8,64}$`) — один на сообщение, повтор отправки — тот же. */
export function newClientMessageId(): string {
  const raw =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return `cm_${raw.replace(/[^A-Za-z0-9]/g, '')}`.slice(0, 64);
}

/** Лента без повторов по `id`, по возрастанию: опрос и ответ отправки складываются в одну ленту. */
export function mergeMessages(current: readonly PortalMessage[], incoming: readonly PortalMessage[]): PortalMessage[] {
  const byId = new Map<number, PortalMessage>();
  for (const message of current) byId.set(message.id, message);
  for (const message of incoming) byId.set(message.id, message);
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

/** Последний id ленты (для `after_id` и «прочитано»); пустая лента — `null`. */
export function lastMessageId(messages: readonly PortalMessage[]): number | null {
  return messages.length > 0 ? messages[messages.length - 1].id : null;
}

/** Последний ответ менеджера в ленте; нет — 0. */
export function lastManagerId(messages: readonly PortalMessage[]): number {
  let last = 0;
  for (const message of messages) if (message.direction === 'manager' && message.id > last) last = message.id;
  return last;
}

/** Отправка в ленте до ответа ERP: `sending` — идёт, `failed` — не ушла («Повторить» тем же ключом). */
export interface PendingMessage {
  clientMessageId: string;
  text: string;
  context: MessageContext | null;
  status: 'sending' | 'failed';
}

/** Отправки, которых ещё нет в ленте ERP (пришедшее с тем же ключом — уже настоящее сообщение). */
export function unsentPending(pending: readonly PendingMessage[], messages: readonly PortalMessage[]): PendingMessage[] {
  const delivered = new Set(messages.map((message) => message.client_message_id).filter(Boolean));
  return pending.filter((item) => !delivered.has(item.clientMessageId));
}
