import type {
  InboundMail,
  InboundMailAddress,
  InboundMailEvent,
  InboundMailPerson,
  InboundMailType,
} from "../shared/api/generated/model";
import { resolveType } from "./mailTypes";

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
  type: null as InboundMailType | null,
} satisfies Partial<StoredMail>;

/** Тело письма, которого нет в карточке верхнего уровня: HTML после санитизации и свёрнутая цитата (P2-4). */
interface Body {
  html?: string;
  remoteImages?: number;
  tail?: string;
}

function make(
  over: Partial<StoredMail> & Pick<StoredMail, "id" | "subject" | "text"> & Body,
): StoredMail {
  const { html, remoteImages, tail, ...fields } = over;
  const receivedAt = over.received_at ?? minutesAgo(60);
  const full: StoredMail = {
    ...BASE,
    status: "new",
    from_email: "client@example.test",
    from_name: "",
    received_at: receivedAt,
    sent_at: receivedAt,
    preview: over.text.slice(0, 120),
    ...fields,
  };
  full.activity_at = over.activity_at ?? full.received_at;
  full.attachments_count = full.attachments.filter((file) => !file.inline).length;
  full.messages = over.messages ?? [
    {
      id: full.id,
      from_email: full.from_email,
      from_name: full.from_name,
      at: full.received_at,
      text: full.text,
      text_tail: tail ?? "",
      html: html ?? null,
      html_remote_images: remoteImages ?? 0,
      attachments: full.attachments,
      new_participant: false,
    },
  ];
  full.reply_to = over.reply_to ?? full.from_email;
  full.reply_options = over.reply_options ?? [full.from_email];
  full.messages_count = full.messages.length;
  return full;
}

const done = (
  outcome: "registered" | "lead" | "replied" | "archived" | "price",
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

const LOGO =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";

/** Рассылка, как её хранит CRM после санитизации: логотип встроен, внешние картинки без `src`, потерянная — заглушка. */
const NEWSLETTER =
  '<table width="600" cellpadding="0" cellspacing="0" bgcolor="#f5f5f5"><tbody><tr>' +
  `<td align="center" style="padding:16px"><img src="${LOGO}" width="48" height="48" alt="Логотип"></td></tr>` +
  '<tr><td style="padding:0 16px"><h1 style="font-size:20px;color:#1f1f1f">Скидки недели на канцтовары</h1>' +
  "<p>Только до пятницы — скидки до 30% на бумагу и картриджи.</p>" +
  '<img data-rt-src="https://cdn.promo-demo.example/banner.png" width="600" alt="Баннер акции"></td></tr>' +
  '<tr><td style="padding:16px"><table width="100%" border="1" cellpadding="6" cellspacing="0"><tbody>' +
  "<tr><td>Бумага А4, 500 листов</td><td>38 000 сум</td></tr>" +
  "<tr><td>Картридж лазерный</td><td>210 000 сум</td></tr></tbody></table>" +
  '<p><img data-rt-missing="1" alt="Фото каталога"></p>' +
  '<p><a href="https://promo-demo.example/sale" target="_blank" rel="noopener noreferrer">Смотреть все предложения</a></p>' +
  '<img data-rt-src="https://track.promo-demo.example/open.gif?u=1" width="1" height="1" alt=""></td></tr></tbody></table>' +
  '<div class="gmail_quote"><blockquote>Вы получили это письмо, потому что подписаны на рассылку.</blockquote></div>';

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
        {
          index: 0,
          name: "акт-сверки-октябрь.pdf",
          content_type: "application/pdf",
          size: 48213,
          inline: false,
        },
      ],
      skipped: [{ name: "macros.xlsm", reason: "type" }],
      inns: ["301234567"],
      client: { id: 42, number: "42", name: "ООО «Демо-Поставка»" },
      assist: {
        status: "done",
        kind: null,
        summary: "Поставщик прислал акт сверки за октябрь, просит подписать до 10 ноября.",
        action: null,
      },
      type: resolveType("supplier_invoice", "ai"),
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
      text: "Скидки недели на канцтовары\n\nТолько до пятницы — скидки до 30% на бумагу и картриджи.\n\nБумага А4 500 л. 38 000 сум\nКартридж лазерный 210 000 сум\n\nСмотреть все предложения",
      html: NEWSLETTER,
      remoteImages: 2,
      attachments: [
        { index: 0, name: "logo.png", content_type: "image/png", size: 95, inline: true },
      ],
      assist: {
        status: "done",
        kind: null,
        summary: "Рекламная рассылка канцтоваров.",
        action: null,
      },
      type: resolveType("mailing", "ai"),
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
      tail: "Иван Демо <ivan@railtech.example> пишет:\n> Добрый день! Подскажите цену смазки на партию из 40 канистр.\n\n--\nДемо-Масла, отдел продаж\n+998 00 000 00 00",
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
          text_tail: "",
          html: null,
          html_remote_images: 0,
          attachments: [],
          new_participant: false,
        },
        {
          id: 122,
          from_email: "finance@pay-demo.example",
          from_name: "Демо-Платёж",
          at: minutesAgo(15),
          text: "Платёж отправили, подтверждение приложили.",
          text_tail:
            "Демо Менеджер <manager@railtech.example> пишет:\n> Реквизиты для оплаты — в приложенном счёте.",
          html: null,
          html_remote_images: 0,
          attachments: [
            {
              index: 0,
              name: "платёжка-118.pdf",
              content_type: "application/pdf",
              size: 20111,
              inline: false,
            },
          ],
          new_participant: false,
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
    make({
      id: 28,
      from_email: "sales@rail-parts-demo.example",
      from_name: "ООО «Демо-Скрепления»",
      subject: "Коммерческое предложение на скрепления КБ-65",
      received_at: minutesAgo(8),
      text:
        "Добрый день!\n\nНаправляем коммерческое предложение и прайс-лист на рельсовые скрепления КБ-65. " +
        "Цены действуют до 30 ноября, поставка со склада в Ташкенте.\n\nОтдел продаж ООО «Демо-Скрепления»",
      attachments: [
        {
          index: 0,
          name: "kp-skrepleniya-kb65.xlsx",
          content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          size: 31844,
          inline: false,
        },
      ],
      assist: {
        status: "done",
        kind: null,
        summary: "Поставщик прислал КП и прайс на скрепления КБ-65, цены до 30 ноября.",
        action: null,
      },
      type: resolveType("supplier_price", "ai"),
    }),
    make({
      id: 29,
      from_email: "info@soliq.example",
      from_name: "Налоговая служба Демо",
      subject: "Требование о предоставлении документов",
      received_at: minutesAgo(12),
      text:
        "Уважаемый руководитель!\n\nВ соответствии с запросом просим представить документы по сделкам за III квартал " +
        "в срок до 15 ноября.\n\nНалоговая служба Демо",
    }),
  ];
}
