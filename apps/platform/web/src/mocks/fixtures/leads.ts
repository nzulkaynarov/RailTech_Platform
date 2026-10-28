import type {
  ClientCard,
  ClientInvitation,
  ClientRow,
  HandoffFacts,
  HandoffInfo,
  LeadCard,
  LeadPlatformStatus,
  LeadRow,
  PersonRef,
} from "../../shared/api/generated/model";

/**
 * Состояние моков «Клиенты · Лиды, Клиенты и „Создать заявку“» (D1-2b, BFF 0.26.0). Данные выдуманы (репозиторий
 * публичный): имена, компании, ИНН и телефоны — демо. Время — относительно момента сброса. Хранится в `localStorage`
 * страницы (ключ `rt-pf-mock-crm-leads`), без хранилища — в памяти; тесты чистят `localStorage` целиком, `resetLeads` —
 * то же для памяти.
 */
const KEY = "rt-pf-mock-crm-leads";
/** `localStorage[...] = "1"`: ERP недоступна — новая заявка не доходит до ERP (`transfer: failed`, «Повторить»). */
export const MOCK_ERP_DOWN_KEY = "rt-pf-mock-erp-down";
/** Сотрудник демо-сессии «Менеджер» — ведёт один из лидов (`scope=mine`). */
export const MOCK_MANAGER_ID = "u-demo-manager";

export interface LeadMockRow {
  row: LeadRow;
  card: LeadCard;
  /** Как в CRM: согласие и канал лида решают отказы «Создать заявку» */
  consent: boolean;
}

export interface LeadsMock {
  leads: LeadMockRow[];
  clients: ClientCard[];
  /** `request_key` → id заявки (повтор формы не создаёт вторую) */
  keys: Record<string, number>;
  nextDeal: number;
  nextClient: number;
  /** NNN следующего номера ЗВ */
  nextNumber: number;
}

const MINUTE = 60_000;

function ago(base: number, minutes: number): string {
  return new Date(base - minutes * MINUTE).toISOString();
}

const MANAGER: PersonRef = { id: MOCK_MANAGER_ID, name: "Демо Менеджеров", initials: "ДМ" };

function facts(over: Partial<HandoffFacts> = {}): HandoffFacts {
  return {
    interest: [],
    timeline: null,
    decision_role: null,
    budget_hint: null,
    company: null,
    company_size: null,
    region: null,
    ...over,
  };
}

function handoff(base: number, over: Partial<HandoffInfo>): HandoffInfo {
  return {
    priority: "hot",
    state: "open",
    reasons: ["price_or_contract_asked"],
    reason_text: null,
    recommendation: null,
    created_at: ago(base, 12),
    sla_due_at: new Date(base + 3 * MINUTE).toISOString(),
    snoozed_until: null,
    taken_by: null,
    ...over,
  };
}

interface Spec {
  id: number;
  name: string;
  status: LeadPlatformStatus;
  channel: string;
  need: string | null;
  minutes: number;
  consent: boolean;
  telegram?: string;
  phone?: string;
  email?: string;
  company?: string;
  assigned?: PersonRef;
  handoff?: Partial<HandoffInfo>;
  overdue?: boolean;
  unread?: boolean;
  clientId?: number;
  interest?: string[];
}

function lead(base: number, spec: Spec): LeadMockRow {
  const number = `L-${String(spec.id).padStart(4, "0")}`;
  const lastAt = ago(base, spec.minutes);
  const info = spec.handoff ? handoff(base, spec.handoff) : null;
  const row: LeadRow = {
    lead: number,
    name: spec.name,
    status: spec.status,
    channel: spec.channel,
    language: "ru",
    assigned: spec.assigned ?? null,
    need: spec.need,
    last_message_at: lastAt,
    unread: spec.unread ?? false,
    handoff_open: info !== null && (info.state === "open" || info.state === "snoozed"),
    overdue: spec.overdue ?? false,
    client_id: spec.clientId ?? null,
  };
  const card: LeadCard = {
    lead: number,
    name: spec.name,
    status: spec.status,
    channel: spec.channel,
    language: "ru",
    assigned: spec.assigned ?? null,
    contacts: {
      telegram: spec.telegram ?? null,
      phone: spec.phone ?? null,
      email: spec.email ?? null,
      company: spec.company ?? null,
    },
    consent: { given_at: spec.consent ? ago(base, 60 * 24) : null, method: null },
    facts: facts({ interest: spec.interest ?? [], company: spec.company ?? null }),
    need: spec.need,
    interest: spec.interest ?? [],
    handoff: info,
    last_messages: spec.need
      ? [
          { author: "lead", text: spec.need, at: ago(base, spec.minutes + 3) },
          {
            author: "bot",
            text: "Уточню у менеджера и вернусь с ответом.",
            at: ago(base, spec.minutes + 2),
          },
          { author: "lead", text: "Сколько это будет стоить?", at: lastAt },
        ]
      : [],
    client: null,
    confirmation: null,
    first_response: { due_at: null, overdue: false },
    invitation: null,
  };
  return { row, card, consent: spec.consent };
}

function invitation(base: number): ClientInvitation {
  return {
    status: "sent",
    channel: "telegram",
    sent_via: ["telegram"],
    sent_at: ago(base, 60 * 26),
    contact_name: "Бобур Снабженцев",
    error_text: null,
    available_channels: ["email", "telegram", "both"],
    suggested_channel: "email",
    can_resend: true,
  };
}

function clientCards(base: number): ClientCard[] {
  const ok = { contacts: "ok", requests: "ok", documents: "ok" } as const;
  return [
    {
      id: 3,
      name: "ООО Рельс-Сервис Демо",
      inn: "300000003",
      segment: "Железные дороги",
      in_erp: true,
      handoff: { status: "done", error: null },
      contacts: [
        {
          id: 31,
          name: "Бобур Снабженцев",
          position: "Начальник снабжения",
          phone: null,
          email: null,
          telegram: "bobur_demo",
          channels: ["telegram"],
          preferred_channel: "telegram",
          is_primary: true,
        },
        {
          id: 32,
          name: "Лола Бухгалтерова",
          position: "Бухгалтер",
          phone: null,
          email: "buh@relservice.example",
          telegram: null,
          channels: ["email"],
          preferred_channel: "email",
          is_primary: false,
        },
      ],
      leads: [
        {
          lead: "L-2033",
          name: "Бобур Снабженцев",
          status: "client",
          last_message_at: ago(base, 90),
        },
        {
          lead: "L-2012",
          name: "Рельс-Сервис (сайт)",
          status: "client",
          last_message_at: ago(base, 60 * 30),
        },
      ],
      requests: [
        {
          deal: 301,
          number: "ПР-2026-018",
          title: "Заявка: ООО Рельс-Сервис Демо",
          summary: "Стрелочные переводы Р65, 4 комплекта",
          step: "PAYMENT",
          project: true,
          client_sees: "awaiting_payment",
          urgency: "normal",
          transfer: "done",
          transfer_error: null,
          created_at: ago(base, 60 * 24 * 20),
          letter_file_id: null,
        },
        {
          deal: 302,
          number: "ЗВ-2026-031",
          title: "Заявка: ООО Рельс-Сервис Демо",
          summary: "Накладки 4-дырные, 600 шт",
          step: "QUOTE",
          project: false,
          client_sees: "awaiting_decision",
          urgency: "urgent",
          transfer: "done",
          transfer_error: null,
          created_at: ago(base, 60 * 24 * 5),
          letter_file_id: null,
        },
        {
          deal: 303,
          number: null,
          title: "Заявка: ООО Рельс-Сервис Демо",
          summary: "Болты закладные, 2000 шт",
          step: "REQUEST",
          project: false,
          client_sees: "in_work",
          urgency: "normal",
          transfer: "failed",
          transfer_error: "erp_unavailable",
          created_at: ago(base, 60 * 3),
          letter_file_id: null,
        },
      ],
      documents: [
        {
          id: 3101,
          title: "Договор поставки",
          type: "contract",
          number: "ДОГ-2026/018",
          date: "2026-10-12",
          visible_to_client: true,
        },
        {
          id: 3102,
          title: "Счёт на предоплату",
          type: "invoice",
          number: "СЧ-2026/044",
          date: "2026-10-15",
          visible_to_client: true,
        },
      ],
      invitation: invitation(base),
      sources: ok,
    },
    {
      id: 4,
      name: "ООО Демо-Вагон",
      inn: "300000004",
      segment: null,
      in_erp: true,
      handoff: { status: "done", error: null },
      contacts: [
        {
          id: 41,
          name: "Тимур Вагонов",
          position: null,
          phone: "+998900000041",
          email: null,
          telegram: null,
          channels: ["phone"],
          preferred_channel: null,
          is_primary: true,
        },
      ],
      leads: [
        {
          lead: "L-2055",
          name: "Тимур Вагонов",
          status: "client",
          last_message_at: ago(base, 60 * 5),
        },
      ],
      requests: [],
      documents: [],
      invitation: null,
      sources: ok,
    },
    {
      id: 5,
      name: "ИП Демо-Путь",
      inn: null,
      segment: null,
      in_erp: false,
      handoff: { status: "failed", error: "erp_inn_conflict" },
      contacts: [],
      leads: [],
      requests: [],
      documents: [],
      invitation: null,
      sources: ok,
    },
    {
      id: 6,
      name: "АО Демо-Терминал",
      inn: "300000006",
      segment: "Порты",
      in_erp: true,
      handoff: { status: "done", error: null },
      contacts: [],
      leads: [],
      requests: [],
      documents: [],
      invitation: null,
      sources: ok,
    },
  ];
}

function initial(): LeadsMock {
  const base = Date.now();
  const leads = [
    lead(base, {
      id: 2041,
      name: "Азиз Демо",
      status: "wants_quote",
      channel: "telegram",
      need: "Рельсы Р65, 40 т",
      minutes: 12,
      consent: true,
      telegram: "aziz_demo",
      company: "ООО Демо-Логистик",
      handoff: {},
      unread: true,
      interest: ["Рельсы"],
    }),
    lead(base, {
      id: 2044,
      name: "Шахноза Демо",
      status: "wants_quote",
      channel: "web",
      need: "Шпалы железобетонные, 300 шт",
      minutes: 40,
      consent: true,
      email: "shakhnoza@demo.example",
      company: "ООО Демо-Строй",
      assigned: MANAGER,
      handoff: { state: "taken", taken_by: MANAGER },
    }),
    lead(base, {
      id: 2048,
      name: "Новый посетитель",
      status: "new",
      channel: "telegram",
      need: null,
      minutes: 3,
      consent: true,
      telegram: "visitor_demo",
    }),
    lead(base, {
      id: 2050,
      name: "Отабек Демо",
      status: "dialog",
      channel: "telegram",
      need: "Подшипники буксовые",
      minutes: 25,
      consent: true,
      telegram: "otabek_demo",
      assigned: MANAGER,
    }),
    lead(base, {
      id: 2060,
      name: "Ждёт ответа Демо",
      status: "no_answer",
      channel: "email",
      need: "Колёсные пары, срочно",
      minutes: 95,
      consent: true,
      email: "wait@demo.example",
      handoff: {
        reasons: ["callback_requested"],
        priority: "warm",
        created_at: ago(base, 95),
        sla_due_at: ago(base, 35),
      },
      overdue: true,
    }),
    lead(base, {
      id: 2033,
      name: "Бобур Снабженцев",
      status: "client",
      channel: "telegram",
      need: "Стрелочные переводы Р65",
      minutes: 90,
      consent: true,
      telegram: "bobur_demo",
      company: "ООО Рельс-Сервис Демо",
      clientId: 3,
    }),
    lead(base, {
      id: 2020,
      name: "Отказ Демо",
      status: "lost",
      channel: "referral",
      need: "Цена ниже рынка",
      minutes: 60 * 48,
      consent: true,
      phone: "+998900000020",
    }),
    lead(base, {
      id: 2077,
      name: "Звонок Демо",
      status: "dialog",
      channel: "phone",
      need: "Тормозные колодки, 200 шт",
      minutes: 50,
      consent: false,
      phone: "+998900000077",
      company: "ООО Демо-Депо",
    }),
  ];
  const client = leads.find((l) => l.row.lead === "L-2033");
  if (client) {
    client.card.client = { id: 3, name: "ООО Рельс-Сервис Демо", inn: "300000003" };
    client.card.invitation = invitation(base);
  }
  return {
    leads,
    clients: clientCards(base),
    keys: {},
    nextDeal: 400,
    nextClient: 10,
    nextNumber: 40,
  };
}

let memory: LeadsMock | null = null;

export function readLeads(): LeadsMock {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as LeadsMock;
  } catch {
    if (memory) return structuredClone(memory);
  }
  if (memory) return structuredClone(memory);
  const state = initial();
  writeLeads(state);
  return state;
}

export function writeLeads(state: LeadsMock): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetLeads(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}

/** Строка списка клиентов из карточки: открытые заявки — не проекты в «Выполнено» и не отказ. */
export function clientRow(card: ClientCard): ClientRow {
  const open = card.requests.filter((r) => r.step !== "DONE" && r.step !== "LOST").length;
  const times = card.leads.map((l) => l.last_message_at).filter((t): t is string => Boolean(t));
  times.sort();
  return {
    id: card.id,
    name: card.name,
    inn: card.inn,
    in_erp: card.in_erp,
    open_requests: open,
    last_activity_at: times.length ? (times[times.length - 1] ?? null) : null,
    handoff_status: card.handoff.status,
  };
}
