import type {
  BusDelivery,
  BusDomain,
  BusInboxEntry,
  BusSubscriber,
  BusSubscriberState,
} from "../../shared/api/generated/model";

/**
 * Состояние Admin · Журнал интеграций для MSW (W13-A2). Вымышленное: внутренние адреса compose, выдуманные номера и
 * id событий, тел событий нет (как и в ответах BFF). Время фиксировано, чтобы снимки и e2e не плавали. Счётчики
 * подписчиков считаются из доставок — повтор в моке меняет и таблицу, и сводку, как в настоящем журнале.
 */
const KEY = "rt-pf-mock-bus";
export const BUS_NOW = "2026-10-26T09:12:00Z";

export interface SubscriberSeed {
  domain: BusDomain;
  name: string;
  endpoint: string | null;
  configured: boolean;
  enabled: boolean;
  drop: boolean;
  /** Ждут сверх строк журнала (очередь большая, в таблицу доставок не выводится) */
  extraPending: number;
  consecutive_failures: number;
  paused_until: string | null;
  last_failure_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
}

export interface BusMock {
  subscribers: SubscriberSeed[];
  deliveries: BusDelivery[];
  inbox: BusInboxEntry[];
  outbox: Record<BusDomain, number>;
}

const HOSTS: Record<string, string> = {
  crm: "crm-api",
  erp: "erp-backend",
  eds: "eds-api",
  "platform-bff": "platform-bff",
};

function sub(domain: BusDomain, name: string, over: Partial<SubscriberSeed> = {}): SubscriberSeed {
  return {
    domain,
    name,
    endpoint: `http://${HOSTS[name] ?? name}:8000/bus/v1/events`,
    configured: true,
    enabled: true,
    drop: false,
    extraPending: 0,
    consecutive_failures: 0,
    paused_until: null,
    last_failure_at: null,
    last_success_at: "2026-10-26T09:11:40Z",
    last_error: null,
    ...over,
  };
}

let nextId = 1000;

function delivery(
  domain: BusDomain,
  subscriber: string,
  eventType: string,
  minute: number,
  over: Partial<BusDelivery> = {},
): BusDelivery {
  nextId += 1;
  const time = `2026-10-26T09:${String(minute).padStart(2, "0")}:00Z`;
  return {
    domain,
    id: nextId,
    event_id: `6f1c2d3e-4b5a-4c6d-8e7f-${String(nextId).padStart(12, "0")}`,
    event_type: eventType,
    subscriber,
    status: "delivered",
    attempts: 1,
    next_attempt_at: null,
    last_attempt_at: time,
    last_status_code: 200,
    last_error: null,
    delivered_at: time,
    created_at: time,
    subject: null,
    correlation_id: `req-${String(nextId)}`,
    ...over,
  };
}

const dead = (code: number, error: string): Partial<BusDelivery> => ({
  status: "dead",
  last_status_code: code,
  last_error: error,
  delivered_at: null,
});

function seedBus(): BusMock {
  nextId = 1000;
  const subscribers = [
    sub("crm", "eds"),
    sub("crm", "erp", {
      consecutive_failures: 0,
      last_failure_at: "2026-10-26T08:58:00Z",
      last_error: "HTTP 404: Not Found",
    }),
    sub("crm", "platform-bff", {
      consecutive_failures: 2,
      extraPending: 3,
      last_failure_at: "2026-10-26T09:10:30Z",
      last_error: "HTTP 503: Service Unavailable",
    }),
    sub("erp", "crm", {
      consecutive_failures: 5,
      extraPending: 11,
      paused_until: "2026-10-26T09:16:00Z",
      last_failure_at: "2026-10-26T09:11:00Z",
      last_success_at: "2026-10-26T08:40:00Z",
      last_error: "ConnectError: connection refused",
    }),
    sub("erp", "eds"),
    sub("erp", "platform-bff"),
    sub("eds", "erp"),
    sub("eds", "platform-bff", { enabled: false, extraPending: 7 }),
  ];
  const deliveries = [
    delivery("crm", "erp", "uz.railtech.crm.client.updated.v1", 1, {
      ...dead(404, "HTTP 404: Not Found"),
      subject: "client/7",
    }),
    delivery("crm", "erp", "uz.railtech.crm.contact.created.v1", 3, {
      ...dead(404, "HTTP 404: Not Found"),
      subject: "contact/31",
    }),
    delivery("crm", "erp", "uz.railtech.crm.client.updated.v1", 5, {
      ...dead(404, "HTTP 404: Not Found"),
      subject: "client/12",
    }),
    delivery("crm", "platform-bff", "uz.railtech.crm.lead.created.v1", 10, {
      status: "pending",
      attempts: 2,
      last_status_code: 503,
      last_error: "HTTP 503: Service Unavailable",
      next_attempt_at: "2026-10-26T09:12:30Z",
      delivered_at: null,
      subject: "L-2041",
    }),
    delivery("crm", "eds", "uz.railtech.identity.user.updated.v1", 9, { subject: "user/4" }),
    delivery("erp", "crm", "uz.railtech.erp.quote.sent.v1", 8, {
      status: "pending",
      attempts: 5,
      last_status_code: null,
      last_error: "ConnectError: connection refused",
      next_attempt_at: "2026-10-26T09:22:00Z",
      delivered_at: null,
      subject: "КП-2026-017",
    }),
    delivery("erp", "crm", "uz.railtech.erp.invoice.issued.v1", 2, {
      ...dead(422, "HTTP 422: payload.amount is not a string"),
      attempts: 1,
      subject: "СЧ-2026-044",
    }),
    delivery("erp", "eds", "uz.railtech.erp.request.created.v1", 7, { subject: "ЗВ-2026-104" }),
    delivery("erp", "platform-bff", "uz.railtech.erp.deal.stage_changed.v1", 11, {
      subject: "ЗВ-2026-104",
    }),
    delivery("eds", "erp", "uz.railtech.eds.letter.resolved.v1", 6, {
      subject: "letter/ВХ-104/26",
    }),
    delivery("eds", "platform-bff", "uz.railtech.eds.approval.decided.v1", 4, {
      status: "pending",
      attempts: 0,
      last_status_code: null,
      next_attempt_at: "2026-10-26T09:04:00Z",
      delivered_at: null,
      last_attempt_at: null,
      subject: "КП-2026-017",
    }),
  ];
  const inbox: BusInboxEntry[] = [
    {
      domain: "crm",
      event_id: "7a1b2c3d-4e5f-4a6b-8c7d-000000000001",
      type: "uz.railtech.erp.deal.won.v1",
      publisher: "erp",
      subject: "ЗВ-2026-098",
      correlation_id: "req-in-1",
      status: "failed",
      attempts: 4,
      error: "ValueError: deal ЗВ-2026-098 is not linked to a client",
      received_at: "2026-10-26T08:50:00Z",
      processed_at: null,
    },
    {
      domain: "erp",
      event_id: "7a1b2c3d-4e5f-4a6b-8c7d-000000000002",
      type: "uz.railtech.crm.client.updated.v1",
      publisher: "crm",
      subject: "client/7",
      correlation_id: "req-in-2",
      status: "received",
      attempts: 1,
      error: "IntegrityError: duplicate INN 300000001",
      received_at: "2026-10-26T09:07:00Z",
      processed_at: null,
    },
    {
      domain: "eds",
      event_id: "7a1b2c3d-4e5f-4a6b-8c7d-000000000003",
      type: "uz.railtech.erp.request.created.v1",
      publisher: "erp",
      subject: "ЗВ-2026-101",
      correlation_id: "req-in-3",
      status: "failed",
      attempts: 4,
      error: "LookupError: employee 12 is not in the projection",
      received_at: "2026-10-26T08:30:00Z",
      processed_at: null,
    },
  ];
  return { subscribers, deliveries, inbox, outbox: { crm: 0, erp: 2, eds: 0 } };
}

let memory: BusMock | null = null;

export function readBus(): BusMock {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as BusMock) : seedBus();
  } catch {
    memory ??= seedBus();
    return memory;
  }
}

export function writeBus(state: BusMock): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetBus(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего очищать.
  }
}

/** Состояние словом — то же правило, что у BFF (`app/bus_journal.py` `subscriber_state`). */
function stateOf(s: Omit<BusSubscriber, "state">): BusSubscriberState {
  if (!s.configured) return "removed";
  if (!s.enabled) return "disabled";
  if (s.paused_until !== null) return "paused";
  if (s.dead > 0) return "dead_letters";
  if (s.consecutive_failures > 0) return "failing";
  return "ok";
}

const ageSeconds = (iso: string) => Math.max(0, (Date.parse(BUS_NOW) - Date.parse(iso)) / 1000);

/** Подписчик для ответа BFF: счётчики — по доставкам журнала, пауза — только будущая. */
export function subscriberView(state: BusMock, seed: SubscriberSeed): BusSubscriber {
  const own = state.deliveries.filter(
    (d) => d.domain === seed.domain && d.subscriber === seed.name,
  );
  const waiting = own.filter((d) => d.status === "pending" || d.status === "in_flight");
  const oldest = waiting.map((d) => ageSeconds(d.created_at));
  const base = {
    name: seed.name,
    configured: seed.configured,
    enabled: seed.enabled,
    drop: seed.drop,
    endpoint: seed.endpoint,
    pending: own.filter((d) => d.status === "pending").length + seed.extraPending,
    in_flight: own.filter((d) => d.status === "in_flight").length,
    dead: own.filter((d) => d.status === "dead").length,
    oldest_undelivered_age_seconds: oldest.length ? Math.max(...oldest) : null,
    consecutive_failures: seed.consecutive_failures,
    paused_until: seed.paused_until && seed.paused_until > BUS_NOW ? seed.paused_until : null,
    last_failure_at: seed.last_failure_at,
    last_success_at: seed.last_success_at,
    last_error: seed.last_error,
  };
  return { ...base, state: stateOf(base) };
}
