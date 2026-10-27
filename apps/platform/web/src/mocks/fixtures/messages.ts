import type {
  ConversationCard,
  HandoffInfo,
  MessageInboxItem,
  TeamNote,
  ThreadMessage,
} from "../../shared/api/generated/model";

/**
 * Состояние моков «Клиенты · Ждут ответа» (D1-1): очередь передач, карточки лидов, переписка, заметки. Данные выдуманы
 * (репозиторий публичный). Время — относительно момента сброса, чтобы таймер SLA показывал «ждёт 12 мин» и «срок прошёл»
 * в любой день. Хранится в `localStorage` страницы (как «База знаний»); без хранилища — в памяти.
 */
const KEY = "rt-pf-mock-messages";
/** `localStorage[...] = "1"`: Telegram «не отвечает» — ответ клиенту падает с 502 (сценарий «Повторить»). */
export const MOCK_TELEGRAM_DOWN_KEY = "rt-pf-mock-telegram-down";
/** `localStorage[...] = "1"`: очередь пуста (пустое состояние экрана). */
export const MOCK_INBOX_EMPTY_KEY = "rt-pf-mock-inbox-empty";

export interface LeadMock {
  item: MessageInboxItem;
  card: ConversationCard;
  messages: ThreadMessage[];
  notes: TeamNote[];
}

export interface MessagesMock {
  leads: LeadMock[];
  nextId: number;
  /** Ключи повтора отправленных ответов → id сообщения («Повторить» не дублирует) */
  sent: Record<string, number>;
}

const MINUTE = 60_000;

function ago(base: number, minutes: number): string {
  return new Date(base - minutes * MINUTE).toISOString();
}

const MANAGER = { id: "u-demo-manager", name: "Демо Менеджеров", initials: "ДМ" };

function handoff(base: number, over: Partial<HandoffInfo>): HandoffInfo {
  return {
    priority: "hot",
    state: "open",
    reasons: ["price_or_contract_asked"],
    reason_text: null,
    recommendation: null,
    created_at: ago(base, 12),
    sla_due_at: ago(base, -3),
    snoozed_until: null,
    taken_by: null,
    ...over,
  };
}

function thread(base: number, lead: string, lines: [ThreadMessage["author"], string][]) {
  return lines.map(([author, text], index): ThreadMessage => ({
    id: Number(lead.slice(2)) * 1000 + index,
    author,
    author_name: author === "manager" ? MANAGER.name : null,
    text,
    created_at: ago(base, lines.length - index + 10),
    attachments: [],
    delivery: null,
    retry_key: null,
  }));
}

function history(): [ThreadMessage["author"], string][] {
  const out: [ThreadMessage["author"], string][] = [];
  for (let i = 1; i <= 15; i += 1) {
    out.push(["lead", `Ранее: вопрос о поставке, часть ${String(i)}`]);
    out.push(["bot", `Ранее: ответ бота по базе знаний, часть ${String(i)}`]);
  }
  return out;
}

function initial(): MessagesMock {
  const base = Date.now();
  const rails: LeadMock = {
    item: {
      lead: "L-2041",
      name: "Азиз Демо",
      group: "handoff",
      language: "ru",
      channel: "telegram",
      unread: true,
      last_message_at: ago(base, 12),
      assigned: null,
      handoff: handoff(base, {
        reason_text: "Просит цену на 40 т",
        recommendation: "Уточнить объём и прислать КП сегодня",
      }),
      note: {
        request: "Рельсы Р65, 40 т, доставка до станции",
        facts: {
          interest: ["Рельсы"],
          timeline: "<3m",
          decision_role: "decision_maker",
          budget_hint: null,
          company: "ООО «Демо-Логистик»",
          company_size: null,
          region: "Ташкентская область",
        },
        last_message: "Сколько будет стоить 40 тонн с доставкой?",
      },
    },
    card: {
      lead: "L-2041",
      name: "Азиз Демо",
      language: "ru",
      channel: "telegram",
      owner_mode: "waiting",
      assigned: null,
      consent_given_at: ago(base, 60),
      contacts: {
        telegram: "aziz_demo",
        phone: "+998900000041",
        email: null,
        company: "ООО «Демо-Логистик»",
      },
      facts: {
        interest: ["Рельсы"],
        timeline: "<3m",
        decision_role: "decision_maker",
        budget_hint: null,
        company: "ООО «Демо-Логистик»",
        company_size: null,
        region: "Ташкентская область",
      },
      request: "Рельсы Р65, 40 т, доставка до станции",
      handoff: null,
      client_in_erp: false,
    },
    messages: thread(base, "L-2041", [
      ...history(),
      ["lead", "Здравствуйте! Нужны рельсы Р65, 40 тонн."],
      ["bot", "Здравствуйте! Рельсы Р65 есть в каталоге. Уточните, пожалуйста, станцию доставки."],
      ["lead", "Станция Демо-Сортировочная. Заявку прикладываю."],
      ["lead", "Сколько будет стоить 40 тонн с доставкой?"],
      ["bot", "Цену и условия назовёт менеджер — передаю ему ваш вопрос."],
    ]),
    notes: [],
  };
  rails.card.handoff = rails.item.handoff;
  const withFile = rails.messages[rails.messages.length - 3];
  if (withFile) {
    withFile.attachments = [
      {
        index: 0,
        name: "Заявка-демо.pdf",
        mime: "application/pdf",
        size: 48_213,
        url: `/api/v1/crm/messages/L-2041/attachments/${String(withFile.id)}/0`,
      },
    ];
  }

  const overdue: LeadMock = {
    item: {
      lead: "L-2047",
      name: "Нигора Пример",
      group: "handoff",
      language: "uz",
      channel: "telegram",
      unread: true,
      last_message_at: ago(base, 41),
      assigned: null,
      handoff: handoff(base, {
        priority: "warm",
        reasons: ["human_requested"],
        created_at: ago(base, 40),
        sla_due_at: ago(base, 10),
      }),
      note: {
        request: "Шпалы деревянные, партия на ремонт пути",
        facts: {
          interest: ["Шпалы"],
          timeline: "<1m",
          decision_role: "influencer",
          budget_hint: null,
          company: null,
          company_size: null,
          region: null,
        },
        last_message: "Menejer bilan gaplashsam bo'ladimi?",
      },
    },
    card: {
      lead: "L-2047",
      name: "Нигора Пример",
      language: "uz",
      channel: "telegram",
      owner_mode: "waiting",
      assigned: null,
      consent_given_at: ago(base, 90),
      contacts: { telegram: "nigora_example", phone: null, email: null, company: null },
      facts: {
        interest: ["Шпалы"],
        timeline: "<1m",
        decision_role: "influencer",
        budget_hint: null,
        company: null,
        company_size: null,
        region: null,
      },
      request: "Шпалы деревянные, партия на ремонт пути",
      handoff: null,
      client_in_erp: false,
    },
    messages: thread(base, "L-2047", [
      ["lead", "Assalomu alaykum! Yog'och shpallar kerak."],
      ["bot", "Assalomu alaykum! Qancha miqdorda kerak?"],
      ["lead", "Menejer bilan gaplashsam bo'ladimi?"],
    ]),
    notes: [],
  };
  overdue.card.handoff = overdue.item.handoff;

  const mine: LeadMock = {
    item: {
      lead: "L-2050",
      name: "Тимур Образцов",
      group: "mine",
      language: "ru",
      channel: "telegram",
      unread: true,
      last_message_at: ago(base, 5),
      assigned: MANAGER,
      handoff: null,
      note: {
        request: "Крепёж для рельсов, повторный заказ",
        facts: {
          interest: ["Крепёж"],
          timeline: "<1m",
          decision_role: "decision_maker",
          budget_hint: null,
          company: "АО «Пример-Путь»",
          company_size: null,
          region: null,
        },
        last_message: "Счёт пришлёте сегодня?",
      },
    },
    card: {
      lead: "L-2050",
      name: "Тимур Образцов",
      language: "ru",
      channel: "telegram",
      owner_mode: "manager",
      assigned: MANAGER,
      consent_given_at: ago(base, 300),
      contacts: {
        telegram: "timur_obrazec",
        phone: null,
        email: "zakupki@example.org",
        company: "АО «Пример-Путь»",
      },
      facts: {
        interest: ["Крепёж"],
        timeline: "<1m",
        decision_role: "decision_maker",
        budget_hint: null,
        company: "АО «Пример-Путь»",
        company_size: null,
        region: null,
      },
      request: "Крепёж для рельсов, повторный заказ",
      handoff: null,
      client_in_erp: true,
    },
    messages: thread(base, "L-2050", [
      ["lead", "Добрый день, нужен крепёж как в прошлый раз."],
      ["manager", "Добрый день! Подготовлю КП на тот же состав."],
      ["lead", "Счёт пришлёте сегодня?"],
    ]),
    notes: [
      {
        id: 1,
        author_name: MANAGER.name,
        text: "Клиент платит после поставки — уточнить у бухгалтера",
        created_at: ago(base, 20),
        visible_to_bot: false,
      },
    ],
  };

  const free: LeadMock = {
    item: {
      lead: "L-2060",
      name: "Лид без имени",
      group: "unassigned",
      language: "en",
      channel: "telegram",
      unread: false,
      last_message_at: ago(base, 120),
      assigned: null,
      handoff: null,
      note: {
        request: null,
        facts: {
          interest: [],
          timeline: null,
          decision_role: null,
          budget_hint: null,
          company: null,
          company_size: null,
          region: null,
        },
        last_message: "Hello, do you ship to Kazakhstan?",
      },
    },
    card: {
      lead: "L-2060",
      name: "Лид без имени",
      language: "en",
      channel: "telegram",
      owner_mode: "waiting",
      assigned: null,
      consent_given_at: null,
      contacts: { telegram: null, phone: null, email: null, company: null },
      facts: {
        interest: [],
        timeline: null,
        decision_role: null,
        budget_hint: null,
        company: null,
        company_size: null,
        region: null,
      },
      request: null,
      handoff: null,
      client_in_erp: false,
    },
    messages: thread(base, "L-2060", [["lead", "Hello, do you ship to Kazakhstan?"]]),
    notes: [],
  };
  // B-013: ответ, доставку которого Telegram так и не подтвердил (таймаут), — пометка и «Повторить» в ленте.
  mine.messages.push({
    id: 2_050_900,
    author: "manager",
    author_name: MANAGER.name,
    text: "Счёт пришлю до конца дня.",
    created_at: ago(base, 4),
    attachments: [],
    delivery: "sending",
    retry_key: "draft-demo-unconfirmed",
  });
  return {
    leads: [rails, overdue, mine, free],
    nextId: 900_000,
    sent: { "draft-demo-unconfirmed": 2_050_900 },
  };
}

let memory: MessagesMock | null = null;

export function readMessages(): MessagesMock {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as MessagesMock;
  } catch {
    if (memory) return structuredClone(memory);
  }
  if (memory) return structuredClone(memory);
  const state = initial();
  writeMessages(state);
  return state;
}

export function writeMessages(state: MessagesMock): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetMessages(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}

export function mockFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}
