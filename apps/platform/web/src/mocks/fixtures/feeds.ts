import type {
  ActivityItem,
  MenuCounter,
  Notification,
  ObjectRef,
  QueueCard,
  QueueItem,
  SearchGroup,
} from "../../shared/api/generated/model";
import { QUEUE, allows, type ResourceKey } from "../../app/rbac.generated";
import { ROLE_ID, type MockRole, type PresetCode } from "./roles";

/**
 * Вымышленные данные Dashboard, уведомлений и поиска для MSW (PLT-14): те же формы, что вернёт BFF по
 * `platform-bff.yaml`, значения — по макету «v3 · 1. Dashboard». Только для моков: боевой код берёт ответ BFF.
 * Названия компаний и имена сотрудников выдуманы (репозиторий публичный).
 */
const HOUR = 3_600_000;
const MINUTE = 60_000;

const seg = (value: string) => encodeURIComponent(value);

const letter: ObjectRef = {
  kind: "letter",
  number: "ВХ-104/26",
  title: "Письмо ВХ-104/26",
  path: `/eds/inbox/${seg("ВХ-104/26")}?panel=open&tab=resolution`,
};
const quote: ObjectRef = {
  kind: "quote",
  number: "КП-2026/118",
  title: "КП-2026/118",
  path: `/eds/drafts/${seg("КП-2026/118")}?panel=open&tab=approve`,
};
const memo: ObjectRef = {
  kind: "memo",
  number: "СЗ-2026/031",
  title: "СЗ-2026/031",
  path: `/eds/approvals/${seg("СЗ-2026/031")}?panel=open&tab=agree`,
};
const request104: ObjectRef = {
  kind: "request",
  number: "ЗВ-2026-104",
  title: "Стрелочные приводы",
  path: `/crm/requests?request=${seg("ЗВ-2026-104")}&panel=open&tab=card`,
  step: "CALCULATION",
};
const project99: ObjectRef = {
  kind: "project",
  number: "ПР-2026-099",
  title: "Рельсовые скрепления",
  path: `/eds/projects/${seg("ПР-2026-099")}?panel=open&tab=documents`,
  step: "PAYMENT",
};
const invoice142: ObjectRef = {
  kind: "invoice",
  number: "СЧ-2026/142",
  title: "СЧ-2026/142",
  path: `/eds/payments/${seg("СЧ-2026/142")}?panel=open&tab=payment`,
};
const contract91: ObjectRef = {
  kind: "contract",
  number: "ДОГ-2026/091",
  title: "ДОГ-2026/091",
  path: `/eds/projects/${seg("ПР-2026-099")}?panel=open&tab=documents`,
};
const lead = (id: number, title: string): ObjectRef => ({
  kind: "lead",
  number: `L-${String(id)}`,
  title,
  path: `/crm/leads?lead=L-${String(id)}&panel=open&tab=card`,
});
/** Лид, от которого ждут ответа (передача бота, новое сообщение): строка очереди и уведомление ведут в диалог «Ждут ответа» (D1-6). */
const leadDialog = (id: number, title: string): ObjectRef => ({
  kind: "lead",
  number: `L-${String(id)}`,
  title,
  path: `/crm/messages?lead=L-${String(id)}`,
});

/** Демо-очередь предустановки (docs/architecture/integration-map.md §1.2); у снабженца, инженера, бухгалтера и админа — пусто. */
function queueFor(preset: PresetCode, now: number): QueueItem[] {
  const role_id = ROLE_ID[preset];
  if (preset === "DIRECTOR") {
    return [
      {
        id: "letter:104",
        role_id,
        kind: "resolve_letter",
        title: "Наложить резолюцию на письмо ВХ-104/26",
        subtitle:
          "ООО «Демо-Депо» · заявка ЗВ-2026-104 · от менеджера Демо Менеджерова · вчера 09:24",
        due_label: "today",
        due_at: new Date(now + 4 * HOUR).toISOString(),
        object: letter,
      },
      {
        id: "quote:118",
        role_id,
        kind: "approve_quote",
        title: "Одобрить КП-2026/118 (черновик)",
        subtitle: "АО «Демо-Рейл» · расчёт готов, визы собраны · маржа 23,4 %",
        due_label: "tomorrow",
        due_at: new Date(now + 28 * HOUR).toISOString(),
        object: quote,
      },
      {
        id: "memo:31",
        role_id,
        kind: "approve_memo",
        title: "Согласовать СЗ-2026/031 · Закупка кофе и воды в офис, 450 000 сум",
        subtitle: "от Демо Офисовой (офис-менеджер) · создана из чата #офис · 2 вложения",
        due_label: "memo",
        object: memo,
      },
    ];
  }
  if (preset === "MANAGER") {
    return [
      {
        id: "lead:2041:take",
        role_id,
        kind: "take_lead",
        title: "Взять в работу лида L-2041",
        subtitle: "ООО «Демо-Депо» · просит КП на стрелочные приводы · 20 мин назад",
        due_label: "today",
        due_at: new Date(now + 2 * HOUR).toISOString(),
        object: leadDialog(2041, "ООО «Демо-Депо»"),
      },
      {
        id: "lead:2050:answer",
        role_id,
        kind: "answer_lead",
        title: "Ответить лиду L-2050",
        subtitle: "Демо Клиентов · уточняет сроки поставки · 3 ч назад",
        due_label: "today",
        object: leadDialog(2050, "Демо Клиентов"),
      },
    ];
  }
  return [];
}

const PROJECTS_CARD: QueueCard = {
  key: "projects_in_work",
  label: "Проекты в работе",
  count: 4,
  hint: "1 ждёт оплаты · 1 в отгрузке",
  path: "/eds/projects",
};

function cardsFor(preset: PresetCode): QueueCard[] {
  switch (preset) {
    case "DIRECTOR":
      return [
        {
          key: "letters_without_resolution",
          label: "Входящие без резолюции",
          count: 1,
          hint: "Документы · Входящие письма",
          path: "/eds/inbox",
        },
        {
          key: "quotes_to_approve",
          label: "КП на одобрение",
          count: 1,
          hint: "Документы · КП на одобрение",
          path: "/eds/drafts",
        },
        {
          key: "memos_to_approve",
          label: "Служебные записки",
          count: 1,
          hint: "Документы · На согласовании",
          path: "/eds/approvals",
        },
        PROJECTS_CARD,
      ];
    case "MANAGER":
      return [
        {
          key: "leads_without_answer",
          label: "Лиды без ответа",
          count: 1,
          hint: "Клиенты · Ждут ответа",
          path: "/crm/messages",
        },
        {
          key: "leads_to_take",
          label: "Лиды без менеджера",
          count: 1,
          hint: "Клиенты · Ждут ответа",
          path: "/crm/messages",
        },
        { ...PROJECTS_CARD, hint: "Документы · Проекты: договоры и акты" },
      ];
    case "ADMIN":
      return [];
    default:
      return [{ ...PROJECTS_CARD, hint: "Документы · Проекты: договоры и акты" }];
  }
}

const PRESETS: readonly PresetCode[] = ["DIRECTOR", "MANAGER", "ACCOUNTANT", "SUPPLY", "ENGINEER"];

/** Вид работы попадает в очередь роли, если её матрица даёт раздел вида (секция `queue` каталога, как в BFF). */
function gives(role: MockRole, kind: QueueItem["kind"]): boolean {
  const need = QUEUE[kind];
  return allows(role.access, need.resource, need.level);
}

/**
 * Очередь ролей «вида»: у предустановки — её демо-строки, у созданной администратором роли — строки любых демо-наборов,
 * которые даёт её матрица. `role_id` — первая роль «вида», которой строка положена.
 */
export function queueForView(view: readonly MockRole[], now = Date.now()): QueueItem[] {
  const rank = { overdue: 0, today: 1, tomorrow: 2, memo: 3, later: 4 } as const;
  const everything = PRESETS.flatMap((preset) => queueFor(preset, now));
  const seen = new Set<string>();
  const items: QueueItem[] = [];
  for (const role of view) {
    for (const item of role.demo ? queueFor(role.demo, now) : everything) {
      if (seen.has(item.id) || !gives(role, item.kind)) continue;
      seen.add(item.id);
      items.push({ ...item, role_id: role.id });
    }
  }
  return items.sort((a, b) => rank[a.due_label] - rank[b.due_label]);
}

/** Что нужно роли для карточки над очередью: вид работы или раздел. */
const CARD_NEEDS: Record<string, QueueItem["kind"] | ResourceKey> = {
  leads_without_answer: "answer_lead",
  leads_to_take: "take_lead",
  letters_without_resolution: "resolve_letter",
  quotes_to_approve: "approve_quote",
  memos_to_approve: "approve_memo",
  projects_in_work: "eds.projects",
};

function cardAllowed(role: MockRole, card: QueueCard): boolean {
  const need = CARD_NEEDS[card.key];
  if (!need) return true;
  return need in QUEUE ? gives(role, need as QueueItem["kind"]) : role.access[need] !== undefined;
}

export function cardsForView(view: readonly MockRole[]): QueueCard[] {
  const everything = PRESETS.flatMap(cardsFor);
  const seen = new Set<string>();
  return view
    .flatMap((role) =>
      (role.demo ? cardsFor(role.demo) : everything).filter((card) => cardAllowed(role, card)),
    )
    .filter((card) => (seen.has(card.key) ? false : (seen.add(card.key), true)))
    .slice(0, 4);
}

/** Бейджи подменю: «Моя очередь» считается по очереди роли, остальное — набор из макетов v3. */
export function menuCountersFor(queueCount: number): MenuCounter[] {
  return [
    { module: "dashboard", section: "queue", count: queueCount, attention: queueCount > 0 },
    { module: "dashboard", section: "projects", count: 4, attention: false },
    { module: "crm", section: "messages", count: 1, attention: true },
    { module: "crm", section: "leads", count: 2, attention: true },
    { module: "eds", section: "inbox", count: 1, attention: true },
    { module: "eds", section: "drafts", count: 1, attention: true },
    { module: "eds", section: "approvals", count: 1, attention: true },
    { module: "eds", section: "payments", count: 2, attention: false },
    { module: "erp", section: "calc", count: 2, attention: true },
  ];
}

const person = (id: string, name: string, initials: string) => ({ id, name, initials });

/** Лента «Сегодня» (макет: 4 записи). Время — от текущего момента, чтобы «сегодня» и «вчера» были верными. */
export function activityToday(now = Date.now()): ActivityItem[] {
  const at = (ms: number) => new Date(now - ms).toISOString();
  return [
    {
      id: "act:1",
      actor: person("u-acc", "Демо Бухгалтерова (бухгалтер)", "ДБ"),
      text: "подтвердила оплату по ПР-2026-099",
      module: "eds",
      at: at(5 * MINUTE),
      object: invoice142,
    },
    {
      id: "act:2",
      actor: person("u-mgr", "Демо Менеджеров", "ДМ"),
      text: "создал заявку ЗВ-2026-104 из лида",
      module: "crm",
      at: at(2 * HOUR),
      object: request104,
    },
    {
      id: "act:3",
      actor: person("u-sup", "Демо Снабженцев", "ДС"),
      text: "подтвердил цену поставщика по БКЗ-24В",
      module: "erp",
      at: at(3 * HOUR),
    },
    {
      id: "act:4",
      actor: person("u-off", "Демо Офисова", "ДО"),
      text: "написала служебку из чата #офис",
      module: "eds",
      at: at(4 * HOUR),
      object: memo,
    },
  ];
}

export interface SeedNotification extends Omit<Notification, "created_at"> {
  /** Сколько миллисекунд назад создано */
  ago: number;
}

const note = (
  id: number,
  tab: Notification["tab"],
  title: string,
  subtitle: string,
  ago: number,
  read: boolean,
  object?: ObjectRef,
): SeedNotification => ({
  id: `erp:${String(id)}`,
  tab,
  title,
  subtitle,
  ago,
  read,
  ...(object ? { object } : {}),
});

/** Уведомления предустановок: у директора три непрочитанных (бейдж «3 новых» из макета). */
export function notificationSeed(preset: PresetCode | undefined): SeedNotification[] {
  switch (preset) {
    case "DIRECTOR":
      return [
        note(
          1,
          "decisions",
          "КП-2026/118 ждёт вашего согласования",
          "ЗВ-2026-104 · АО «Демо-Рейл» · срок завтра 18:00",
          5 * MINUTE,
          false,
          quote,
        ),
        note(
          2,
          "decisions",
          "Клиент согласовал проект договора ДОГ-2026/091",
          "следующий шаг: подписать у оператора",
          32 * MINUTE,
          false,
          contract91,
        ),
        note(
          3,
          "clients",
          "Демо Платёжников (Демо-Метро) нажал «Я оплатил»",
          "СЧ-2026/142 · платёжка приложена · бухгалтеру на подтверждение",
          HOUR,
          false,
          invoice142,
        ),
        note(
          4,
          "clients",
          "Лид L-2044 с веб-формы без ответа 2 ч 10 мин",
          "контакт без Telegram · письмо-подтверждение отправлено",
          2 * HOUR,
          true,
          leadDialog(2044, "Лид с веб-формы"),
        ),
        note(
          6,
          "decisions",
          "Письмо ВХ-104/26 ждёт резолюции",
          "ООО «Демо-Депо» · срок сегодня",
          3 * HOUR,
          true,
          letter,
        ),
        note(
          7,
          "decisions",
          "СЗ-2026/031 на согласовании",
          "от Демо Офисовой (офис-менеджер) · 450 000 сум",
          5 * HOUR,
          true,
          memo,
        ),
        note(
          5,
          "system",
          "Почта: DKIM не настроен — письма клиентам могут попадать в спам",
          "Настройки · Подключения",
          20 * HOUR,
          true,
        ),
      ];
    case "MANAGER":
      return [
        note(
          11,
          "decisions",
          "Лид L-2041 просит КП — срок ответа сегодня",
          "ООО «Демо-Депо» · передача от бота",
          10 * MINUTE,
          false,
          leadDialog(2041, "ООО «Демо-Депо»"),
        ),
        note(
          12,
          "clients",
          "Клиент открыл КП-2026/118",
          "ЗВ-2026-104 · АО «Демо-Рейл»",
          3 * HOUR,
          false,
          request104,
        ),
      ];
    case "ACCOUNTANT":
      return [
        note(
          21,
          "decisions",
          "Платёжка получена: СЧ-2026/142",
          "ПР-2026-099 · к подтверждению",
          15 * MINUTE,
          false,
          invoice142,
        ),
      ];
    case "ADMIN":
      return [
        note(
          31,
          "system",
          "Почта: DKIM не настроен — письма клиентам могут попадать в спам",
          "Настройки · Подключения",
          20 * HOUR,
          false,
        ),
      ];
    default:
      return [];
  }
}

interface SearchEntry {
  module: "crm" | "eds";
  /** Раздел матрицы, который открывает результат */
  resource: string;
  object: ObjectRef;
  title: string;
  subtitle?: string;
}

const SEARCH_INDEX: readonly SearchEntry[] = [
  {
    module: "crm",
    resource: "crm.leads",
    object: lead(2041, "ООО «Демо-Депо»"),
    title: "ООО «Демо-Депо»",
    subtitle: "L-2041 · просит КП на стрелочные приводы",
  },
  {
    module: "crm",
    resource: "crm.clients",
    object: {
      kind: "client",
      number: "17",
      title: "ООО «Демо-Депо»",
      path: "/crm/clients/17?panel=open&tab=card",
    },
    title: "ООО «Демо-Депо»",
    subtitle: "ИНН 300000001",
  },
  {
    module: "crm",
    resource: "crm.clients",
    object: request104,
    title: "ЗВ-2026-104 · Стрелочные приводы",
    subtitle: "ООО «Демо-Депо» · Расчёт",
  },
  {
    module: "eds",
    resource: "eds.projects",
    object: project99,
    title: "ПР-2026-099 · Рельсовые скрепления",
    subtitle: "АО «Демо-Рейл» · Оплата",
  },
  {
    module: "eds",
    resource: "eds.inbox",
    object: letter,
    title: "Письмо ВХ-104/26",
    subtitle: "Запрос на стрелочные приводы",
  },
  {
    module: "eds",
    resource: "eds.drafts",
    object: quote,
    title: "КП-2026/118",
    subtitle: "Стрелочные приводы",
  },
  {
    module: "eds",
    resource: "eds.memo.approve",
    object: memo,
    title: "СЗ-2026/031",
    subtitle: "Закупка кофе и воды в офис",
  },
  {
    module: "eds",
    resource: "eds.payments",
    object: invoice142,
    title: "СЧ-2026/142",
    subtitle: "Рельсовые скрепления",
  },
  {
    module: "eds",
    resource: "eds.projects",
    object: contract91,
    title: "ДОГ-2026/091",
    subtitle: "Рельсовые скрепления",
  },
];

/** Поиск по подстроке без учёта регистра; результаты — группами по модулям, только разделы, видимые роли. */
export function searchIndex(
  query: string,
  resources: ReadonlySet<string>,
  withoutEds = false,
): SearchGroup[] {
  const needle = query.trim().toLowerCase();
  const found = SEARCH_INDEX.filter((entry) => {
    if (!resources.has(entry.resource)) return false;
    // EDS не отвечает: письма и служебки не находятся
    if (withoutEds && (entry.object.kind === "letter" || entry.object.kind === "memo"))
      return false;
    const haystack = [entry.object.number, entry.title, entry.subtitle ?? ""]
      .join(" ")
      .toLowerCase();
    return haystack.includes(needle);
  });
  return (["crm", "eds"] as const)
    .map((module) => ({
      module,
      items: found
        .filter((entry) => entry.module === module)
        .map((entry) => ({
          object: entry.object,
          title: entry.title,
          ...(entry.subtitle ? { subtitle: entry.subtitle } : {}),
        })),
    }))
    .filter((group) => group.items.length > 0);
}
