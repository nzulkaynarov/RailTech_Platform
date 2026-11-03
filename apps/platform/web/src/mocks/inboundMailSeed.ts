import type {
  InboundMail,
  InboundMailAddress,
  InboundMailEvent,
  InboundMailPerson,
} from "../shared/api/generated/model";

/**
 * Начальные письма мока общего ящика (W18A-P2, W18A-P2-3). Данные вымышленные. «Я» в моках — сотрудник сессии: его id
 * подставляется при чтении (`ME`), поэтому «в работе у меня» совпадает с `Me.id` (в настоящем BFF это числовой id CRM).
 */
export const ME = "me";
export const COLLEAGUE: InboundMailPerson = { id: 7001, name: "Иванов Демо" };
export const STAFF_UNIVERSAL: InboundMailPerson = {
  id: "u-demo-universal" as unknown as number,
  name: "Демо Широков",
};
export const MAILBOX = "info@company.example";

export type StoredMail = InboundMail;

export function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

const addr = (email: string, staff: InboundMailPerson | null = null): InboundMailAddress => ({
  email,
  staff,
  mailbox: email === MAILBOX,
});

const BASE = {
  activity_at: "",
  cc: [] as InboundMailAddress[],
  to: [addr(MAILBOX)],
  skipped: [],
  too_large: false,
  inns: [],
  lead: null,
  client: null,
  from_history: false,
  assignee: null,
  assigned_at: null,
  personal: false,
  thread_reply: false,
  unread: true,
  messages_count: 1,
  eds_waiting: false,
  result: null,
  replies: [],
  journal: [] as InboundMailEvent[],
  reply_all_copy: [] as string[],
  personal_label: "Адресовано лично",
  reply_to: "",
  reply_options: [] as string[],
  messages: [],
  attachments: [],
  attachments_count: 0,
  assist: { status: "none", kind: null, summary: null, action: null },
} satisfies Partial<StoredMail>;

function make(over: Partial<StoredMail> & Pick<StoredMail, "id" | "subject" | "text">): StoredMail {
  const receivedAt = over.received_at ?? minutesAgo(60);
  const full: StoredMail = {
    ...BASE,
    status: "new",
    from_email: "client@example.test",
    from_name: "",
    received_at: receivedAt,
    sent_at: receivedAt,
    preview: over.text.slice(0, 120),
    ...over,
  };
  full.activity_at = over.activity_at ?? full.received_at;
  full.attachments_count = full.attachments.length;
  full.messages = over.messages ?? [
    {
      id: full.id,
      from_email: full.from_email,
      from_name: full.from_name,
      at: full.received_at,
      text: full.text,
      attachments: full.attachments,
      new_participant: false,
    },
  ];
  full.messages = full.messages.map((m) => ({ ...m, new_participant: m.new_participant ?? false }));
  full.reply_to = over.reply_to ?? full.from_email;
  full.reply_options = over.reply_options ?? [full.from_email];
  full.messages_count = full.messages.length;
  return full;
}

const done = (
  outcome: "registered" | "lead" | "replied" | "archived",
  minutes: number,
  extra: Partial<NonNullable<StoredMail["result"]>> = {},
): Pick<StoredMail, "status" | "result"> => ({
  status: "done",
  result: {
    outcome,
    by: COLLEAGUE,
    at: minutesAgo(minutes),
    letter_number: null,
    letter_ref: null,
    lead: null,
    reason: null,
    ...extra,
  },
});

export function seed(): StoredMail[] {
  return [
    make({
      id: 17,
      from_email: "buh@supplier-demo.example",
      from_name: "ООО «Демо-Поставка»",
      subject: "Акт сверки за октябрь",
      received_at: minutesAgo(25),
      text:
        "Добрый день!\n\nНаправляем акт сверки взаимных расчётов за октябрь 2026 года. Просим подписать и " +
        "вернуть скан до 10 ноября.\n\nС уважением,\nбухгалтерия ООО «Демо-Поставка»\nИНН 301234567",
      attachments: [
        { index: 0, name: "акт-сверки-октябрь.pdf", content_type: "application/pdf", size: 48213 },
      ],
      skipped: [{ name: "macros.xlsm", reason: "type" }],
      inns: ["301234567"],
      client: { id: 42, number: "42", name: "ООО «Демо-Поставка»" },
      assist: {
        status: "done",
        kind: "supplier_doc",
        summary: "Поставщик прислал акт сверки за октябрь, просит подписать до 10 ноября.",
        action: "register",
      },
      to: [addr(MAILBOX), addr("buh.copy@company.example")],
      cc: [addr("sidorov@railtech.example")],
      reply_all_copy: ["buh.copy@company.example", "sidorov@railtech.example"],
    }),
    make({
      id: 18,
      from_email: "zakaz@rail-client-demo.example",
      from_name: "Алия Демо",
      subject: "Запрос КП на стрелочные переводы",
      received_at: minutesAgo(70),
      text:
        "Здравствуйте.\n\nПросим направить коммерческое предложение на 6 стрелочных переводов Р65 с поставкой " +
        "в Ташкент до конца года.\n\nАлия Демо, отдел снабжения",
      unread: false,
    }),
    make({
      id: 19,
      from_email: "news@promo-demo.example",
      from_name: "Промо-рассылка",
      subject: "Скидки недели на канцтовары",
      received_at: minutesAgo(180),
      text: "Только до пятницы — скидки до 30% на бумагу и картриджи.",
      assist: {
        status: "done",
        kind: "other",
        summary: "Рекламная рассылка канцтоваров.",
        action: "archive",
      },
    }),
    make({
      id: 20,
      status: "spam",
      from_email: "tender@zavod-demo.example",
      from_name: "АО «Демо-Завод»",
      subject: "Приглашение к участию в тендере на поставку шпал",
      received_at: minutesAgo(240),
      text:
        "Добрый день!\n\nПриглашаем принять участие в закупке железобетонных шпал. Документация во вложении, " +
        "приём заявок до 20 ноября.\n\nОтдел закупок АО «Демо-Завод»",
    }),
    make({
      id: 21,
      status: "in_work",
      from_email: "snab@oil-demo.example",
      from_name: "Демо-Масла",
      subject: "Счёт на смазку для стрелок",
      received_at: minutesAgo(95),
      text: "Выставляем счёт на смазку для стрелочных переводов, оплата в течение 5 дней.",
      assignee: COLLEAGUE,
      assigned_at: minutesAgo(40),
      unread: false,
      journal: [{ at: minutesAgo(40), action: "take", actor: COLLEAGUE, detail: null }],
    }),
    make({
      id: 22,
      from_email: "finance@pay-demo.example",
      from_name: "Демо-Платёж",
      subject: "Re: Счёт на оплату № 118",
      received_at: minutesAgo(15),
      text: "Платёж отправили, подтверждение приложили.",
      thread_reply: true,
      assignee: COLLEAGUE,
      assigned_at: minutesAgo(300),
      messages: [
        {
          id: 22,
          from_email: "finance@pay-demo.example",
          from_name: "Демо-Платёж",
          at: minutesAgo(320),
          text: "Здравствуйте. Подскажите реквизиты для оплаты счёта № 118.",
          attachments: [],
        },
        {
          id: 122,
          from_email: "finance@pay-demo.example",
          from_name: "Демо-Платёж",
          at: minutesAgo(15),
          text: "Платёж отправили, подтверждение приложили.",
          attachments: [
            { index: 0, name: "платёжка-118.pdf", content_type: "application/pdf", size: 20111 },
          ],
        },
      ],
      replies: [
        {
          id: 1,
          to_email: "finance@pay-demo.example",
          subject: "Re: Счёт на оплату № 118",
          status: "sent",
          created_at: minutesAgo(290),
          sent_at: minutesAgo(290),
          by: COLLEAGUE,
        },
      ],
      journal: [
        { at: minutesAgo(300), action: "take", actor: COLLEAGUE, detail: null },
        { at: minutesAgo(290), action: "reply", actor: COLLEAGUE, detail: null },
        { at: minutesAgo(15), action: "thread_reply", actor: null, detail: null },
      ],
    }),
    make({
      id: 23,
      status: "in_work",
      from_email: "service@depot-demo.example",
      from_name: "Депо Демо",
      subject: "Вопрос по гарантии на стрелочный привод",
      received_at: minutesAgo(50),
      text: "Подскажите, действует ли гарантия на привод после замены контроллера?",
      to: [addr("shirokov@railtech.example", STAFF_UNIVERSAL)],
      cc: [addr(MAILBOX)],
      personal: true,
      assignee: STAFF_UNIVERSAL,
      assigned_at: minutesAgo(50),
      journal: [{ at: minutesAgo(50), action: "personal", actor: null, detail: null }],
    }),
    make({
      id: 24,
      from_email: "gnk@tax-demo.example",
      from_name: "Налоговая инспекция Демо",
      subject: "Уведомление о сверке",
      received_at: minutesAgo(600),
      text: "Просим явиться для сверки расчётов.",
      unread: false,
      ...done("registered", 500, {
        letter_number: "ВХ-42/26",
        letter_ref: "/eds/inbox/%D0%92%D0%A5-42%2F26",
      }),
    }),
    make({
      id: 25,
      from_email: "buyer@lead-demo.example",
      from_name: "Покупатель Демо",
      subject: "Нужна партия рельсов Р65",
      received_at: minutesAgo(700),
      text: "Интересует партия рельсов Р65, 120 тонн.",
      unread: false,
      ...done("lead", 600, {
        lead: { id: 2075, number: "L-2075", name: "Покупатель Демо" },
      }),
    }),
    make({
      id: 26,
      from_email: "news@digest-demo.example",
      from_name: "Дайджест отрасли",
      subject: "Новости отрасли за неделю",
      received_at: minutesAgo(900),
      text: "Подборка новостей отрасли за неделю.",
      unread: false,
      ...done("archived", 800, { reason: "Рассылка" }),
    }),
    make({
      id: 27,
      from_email: "logist@cargo-demo.example",
      from_name: "Демо-Карго",
      subject: "Сроки доставки партии",
      received_at: minutesAgo(1100),
      text: "Подскажите ориентировочные сроки доставки партии в Самарканд.",
      unread: false,
      ...done("replied", 1000),
    }),
  ];
}
