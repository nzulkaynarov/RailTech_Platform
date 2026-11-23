import { legacySettingsPath, SETTINGS_REDIRECTS_REMOVE_AFTER } from "./admin/redirects";

/**
 * Старые адреса разделов → новые (ЕВ-3б, правило 24 доклада 2026-11-22): закладки, письма, колокольчик и «Что нового» не
 * ломаются, а сами разделы-перенаправления из кода убраны. Одна таблица на все модули: у строки есть дата, после которой её
 * удаляют (тест `legacyRedirects.test.ts` краснеет после даты — строку убирают вместе со ссылками, которые на неё ещё ведут).
 * Чистая функция: адрес → новый адрес или `undefined` (адрес действующий). Адреса Настроек — `admin/redirects.ts`.
 */
export interface LegacyRedirect {
  /** Старый путь списка (без хвоста) */
  path: string;
  /** Что считать «старым»: по умолчанию весь путь, `listOnly` — только сам список (карточка `/<path>/:id` живая) */
  listOnly?: boolean;
  /** С карточкой `/<path>/<id>` тоже: `id` — сегмент пути */
  withId?: boolean;
  /** Новый адрес или `undefined`, если запрос не старый (например, другой фильтр) */
  to: (query: URLSearchParams, id?: string) => string | undefined;
  /** Дата ISO (включительно): после неё строку удаляют */
  removeAfter: string;
}

const REMOVE_AFTER = "2027-04-01";

const enc = encodeURIComponent;

export const LEGACY_REDIRECTS: readonly LegacyRedirect[] = [
  // Главная · Проекты — реестр проектов Документов (ЕВ-3а)
  { path: "/dashboard/projects", to: () => "/eds/projects", removeAfter: REMOVE_AFTER },
  // «Ждут ответа» — фильтр «Лидов»: ссылки из колокольчика и задач ведут туда же
  {
    path: "/crm/messages",
    to: (query) => {
      const lead = query.get("lead");
      return `/crm/leads?scope=waiting${lead ? `&lead=${enc(lead)}` : ""}`;
    },
    removeAfter: REMOVE_AFTER,
  },
  // Заявки — в «Операциях», подключение бота — в настройках Telegram
  { path: "/crm/requests", to: () => "/erp/requests", removeAfter: REMOVE_AFTER },
  { path: "/crm/channels", to: () => "/admin/telegram", removeAfter: REMOVE_AFTER },
  // Реестр исходящих — «Исходящие»; КП открывается своей карточкой
  {
    path: "/eds/outbox",
    withId: true,
    to: (query, id) => {
      const search = query.toString();
      return id
        ? `/eds/drafts/${enc(id)}${search ? `?${search}` : ""}`
        : "/eds/documents?box=outgoing";
    },
    removeAfter: REMOVE_AFTER,
  },
  // Старые списки без пункта меню: что ждёт сотрудника — в «Задачах», остальное — в ящиках «Документов»
  {
    path: "/eds/drafts",
    listOnly: true,
    to: (query) => {
      const quote = query.get("quote");
      return quote ? `/eds/drafts/${enc(quote)}` : "/eds/documents?box=outgoing&kind=quote";
    },
    removeAfter: REMOVE_AFTER,
  },
  { path: "/eds/tasks", listOnly: true, to: () => "/dashboard/queue", removeAfter: REMOVE_AFTER },
  {
    path: "/eds/approvals",
    listOnly: true,
    to: (query) => {
      const memo = query.get("memo");
      return memo ? `/eds/approvals/${enc(memo)}` : "/eds/documents?box=internal";
    },
    removeAfter: REMOVE_AFTER,
  },
  // «Мои расчёты» стали фильтром списка заявок
  {
    path: "/erp/calc",
    listOnly: true,
    to: () => "/erp/requests?mine=1",
    removeAfter: REMOVE_AFTER,
  },
  // Смена реквизитов переехала в «Контакты · Контрагенты»
  {
    path: "/eds/payments",
    listOnly: true,
    to: (query) =>
      query.get("show") === "bank_changes" ? "/crm/clients?kind=bank_changes" : undefined,
    removeAfter: REMOVE_AFTER,
  },
  // Партнёры и заявки на подключение переехали из каталога в «Контакты · Контрагенты»
  {
    path: "/erp/catalog",
    listOnly: true,
    to: (query) => {
      const part = query.get("part");
      if (part === "applications") return "/crm/clients?kind=applications";
      if (part !== "suppliers") return undefined;
      const id = query.get("supplier");
      return id
        ? `/crm/clients?partner=${enc(id)}&panel=open&tab=card`
        : "/crm/clients?kind=partners";
    },
    removeAfter: REMOVE_AFTER,
  },
  // Чаты: внутренние — сам список, переписка с клиентами — «Лиды · Ждут ответа»
  {
    path: "/chats",
    listOnly: true,
    to: (query) => {
      const scope = query.get("scope");
      if (scope === "internal") return "/chats";
      if (scope === "external") return "/crm/leads?scope=waiting";
      return undefined;
    },
    removeAfter: REMOVE_AFTER,
  },
];

/** Даты всех строк, включая адреса Настроек — для проверки срока. */
export const LEGACY_REMOVE_DATES: readonly string[] = [
  ...LEGACY_REDIRECTS.map((entry) => entry.removeAfter),
  SETTINGS_REDIRECTS_REMOVE_AFTER,
];

function trimmed(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

export function legacyPath(pathname: string, search = ""): string | undefined {
  const path = trimmed(pathname);
  const query = new URLSearchParams(search);
  for (const entry of LEGACY_REDIRECTS) {
    let id: string | undefined;
    if (path !== entry.path) {
      if (entry.listOnly || !entry.withId || !path.startsWith(`${entry.path}/`)) continue;
      id = decodeURIComponent(path.slice(entry.path.length + 1));
    }
    const target = entry.to(query, id);
    // «/chats?scope=internal» → «/chats»: адрес без фильтра уже действующий, цикла быть не должно
    if (target !== undefined && target !== `${path}${search}`) return target;
  }
  return legacySettingsPath(pathname, search) ?? undefined;
}
