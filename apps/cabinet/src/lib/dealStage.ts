import type { Act, ClientRequest, Contract, DeliveryLine, Invoice, QuoteListItem } from '@/api/portal';

/**
 * Этапы проекта глазами клиента: «Запрос — КП — Договор — Оплата — Поставка и акт» (CAB-FIX-1, аудит K5; клиенту
 * сделка — «проект», SPEC-v3 §2, CAB-FIX-3).
 *
 * Этап считается по **статусам** документов сделки из ответов портала, а не по их наличию. Каждый этап — сам по себе:
 * процесс не обязан быть линейным (счёт на предоплату может прийти раньше подписания договора), поэтому «в работе»
 * могут быть два этапа сразу. Правила:
 *
 * - **Запрос** — показывается, только если запрос сделки есть в списке. Выполнен, когда по нему отправлено КП
 *   (есть КП или статус запроса `quoted`); иначе — в работе.
 * - **КП** — выполнено, когда хотя бы одно КП `accepted`. В работе, если КП есть, но ни одно не принято (ждёт решения,
 *   отклонено и ждёт новой версии, срок истёк). Иначе — впереди.
 * - **Договор** (без `cancelled`) — выполнен, когда договор `signed` (подписан сторонами). В работе, если договор есть
 *   в любом другом статусе (ждёт согласования клиента, согласован клиентом и ждёт подписания) или КП принято, а договор
 *   ещё формируется. Иначе — впереди.
 * - **Оплата** (счета без `cancelled`) — выполнена, когда счета есть и все `paid`. В работе, если есть неоплаченный
 *   счёт (к оплате, частично, просрочен). Иначе — впереди. «Выполнена» значит «оплачено всё выставленное»: будущих
 *   счетов портал не знает.
 * - **Поставка и акт** — выполнены, когда акты есть, все `accepted`, и каждая строка поставки `delivered` или
 *   `accepted`. В работе, если есть акт или строка поставки в другом состоянии. Иначе — впереди.
 *
 * **Текущий этап** (`current`, CAB-FIX-3) — ровно один: первый невыполненный. Экран выделяет только его; остальные
 * начатые (`active`) показываются спокойнее, как «начато».
 *
 * **Закрытый запрос** (`closed`): ERP закрывает сделку и выигранной, и проигранной, а портал не говорит, какой из
 * двух. Поэтому догадки нет: показываются только выполненные этапы (запрос — всегда), ни один не «в работе»,
 * и экран пишет «Запрос закрыт»; текущего этапа нет.
 */
export type DealStageId = 'request' | 'quote' | 'contract' | 'payment' | 'delivery';
export type DealStageState = 'done' | 'active' | 'upcoming';

export interface DealStage {
  id: DealStageId;
  state: DealStageState;
  /** Текущий этап — первый невыполненный; у закрытого запроса текущего нет. */
  current: boolean;
}

export interface DealProgress {
  closed: boolean;
  stages: DealStage[];
}

export interface DealDocuments {
  requests: Pick<ClientRequest, 'status'>[];
  quotes: Pick<QuoteListItem, 'status'>[];
  contracts: Pick<Contract, 'status'>[];
  invoices: Pick<Invoice, 'status'>[];
  acts: Pick<Act, 'status'>[];
  deliveries: Pick<DeliveryLine, 'status'>[];
}

const DELIVERED: ReadonlyArray<DeliveryLine['status']> = ['delivered', 'accepted'];

function state(done: boolean, active: boolean): DealStageState {
  return done ? 'done' : active ? 'active' : 'upcoming';
}

export function dealProgress(docs: DealDocuments): DealProgress {
  const quoteAccepted = docs.quotes.some((quote) => quote.status === 'accepted');
  const contracts = docs.contracts.filter((contract) => contract.status !== 'cancelled');
  const invoices = docs.invoices.filter((invoice) => invoice.status !== 'cancelled');

  const stages: Omit<DealStage, 'current'>[] = [];
  if (docs.requests.length > 0) {
    const quoted = docs.quotes.length > 0 || docs.requests.some((request) => request.status === 'quoted');
    stages.push({ id: 'request', state: state(quoted, true) });
  }
  stages.push(
    { id: 'quote', state: state(quoteAccepted, docs.quotes.length > 0) },
    {
      id: 'contract',
      state: state(
        contracts.some((contract) => contract.status === 'signed'),
        contracts.length > 0 || quoteAccepted,
      ),
    },
    {
      id: 'payment',
      state: state(invoices.length > 0 && invoices.every((invoice) => invoice.status === 'paid'), invoices.length > 0),
    },
    {
      id: 'delivery',
      state: state(
        docs.acts.length > 0 &&
          docs.acts.every((act) => act.status === 'accepted') &&
          docs.deliveries.every((line) => DELIVERED.includes(line.status)),
        docs.acts.length > 0 || docs.deliveries.length > 0,
      ),
    },
  );

  const closed = docs.requests.length > 0 && docs.requests.every((request) => request.status === 'closed');
  if (closed) {
    return {
      closed,
      stages: stages
        .map((stage): DealStage => ({ id: stage.id, state: stage.id === 'request' ? 'done' : stage.state, current: false }))
        .filter((stage) => stage.state === 'done'),
    };
  }
  const currentIndex = stages.findIndex((stage) => stage.state !== 'done');
  return { closed, stages: stages.map((stage, index) => ({ ...stage, current: index === currentIndex })) };
}
