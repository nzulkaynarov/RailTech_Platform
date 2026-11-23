/**
 * Старые адреса Настроек → новые (SET-IA): закладки, ссылки справки, «Что нового» и письма не ломаются. До SET-IA были
 * «Telegram-бот» (`/admin/bot?part=…&section=…`), «Компания и бланки» (`/admin/company?tab=…`), «Документооборот»
 * (`/admin/docflow?tab=…`), список «Обращений сотрудников» (`/admin/tickets`) и карточки «Подключений» `?card=telegram|mail|spend`,
 * которые теперь — свои страницы. Чистая функция: адрес → новый адрес или `null` (адрес действующий).
 */

/** Раздел «Поведения и передачи» бота → страница, куда он переехал. */
const BOT_SECTION: Record<string, string> = {
  company: "/admin/company?part=contacts",
  business_hours: "/admin/timing",
  escalation: "/admin/telegram?tab=behavior",
  bot: "/admin/telegram?tab=behavior",
  stop_words: "/admin/telegram?tab=behavior",
  competitors: "/admin/telegram?tab=behavior",
  qualification: "/admin/telegram?tab=behavior",
  web_form: "/admin/web-forms",
  notifications: "/admin/notifications",
  service_alerts: "/admin/notifications",
  deals: "/admin/dictionaries?list=deals",
  budget: "/admin/ai-spend",
  texts: "/admin/telegram?tab=texts",
  kb: "/admin/telegram?tab=kb",
  templates: "/admin/telegram?tab=templates",
  exports: "/admin/exports",
};

const BOT_PART: Record<string, string> = {
  connection: "/admin/telegram",
  texts: "/admin/telegram?tab=texts",
  behavior: "/admin/telegram?tab=behavior",
  kb: "/admin/telegram?tab=kb",
  templates: "/admin/telegram?tab=templates",
  exports: "/admin/exports",
};

/** Вкладки «Компании и бланков». Реквизиты и бланк остаются на `/admin/company` — секциями одной страницы. */
const COMPANY_TAB: Record<string, string> = {
  details: "/admin/company",
  brand: "/admin/company?part=brand",
  numbering: "/admin/numbering",
  quote: "/admin/sales", // «Условия КП» разошлись по страницам (ДОК-13): «Продажи», «Налоги и валюты», «Уведомления»
  charges: "/admin/dictionaries?list=charges",
  templates: "/admin/templates?tab=documents", // бывшая вкладка — шаблоны документов, не «Все шаблоны»
  reference: "/admin/dictionaries?list=countries",
  categories: "/admin/dictionaries?list=categories",
  platform: "/admin/taxes",
};

const DOCFLOW_TAB: Record<string, string> = {
  dictionaries: "/admin/dictionaries?list=doc",
  templates: "/admin/templates?tab=resolutions",
  ai: "/admin/ai-spend",
};

/** Карточки «Подключений», у которых теперь своя страница. */
const INTEGRATION_CARD: Record<string, string> = {
  telegram: "/admin/telegram",
  mail: "/admin/mail",
  spend: "/admin/ai-spend",
};

export const TICKETS_HOME = "/dashboard/queue";

/**
 * ЕВ-2а (2026-11-23): «Шаблоны резолюций» стали вкладкой «Шаблонов», «Виды писем и правила отправителей» — частью страницы
 * «Почта». Перенос — по таблице ниже; запись с датой, чтобы устаревшие строки можно было снять.
 */
const MAIL_KINDS_LIST = /^(doc:)?mail-types$/;

/** Что открыто в боковом окне бота — текст или шаблон ответа — переносится на новый адрес (ссылки на конкретный текст). */
const CARRIED = ["text", "template", "panel"] as const;

function withCarried(target: string, from: URLSearchParams): string {
  const [path = "", search = ""] = target.split("?");
  const next = new URLSearchParams(search);
  for (const key of CARRIED) {
    const value = from.get(key);
    if (value !== null) next.set(key, value);
  }
  const query = next.toString();
  return query ? `${path}?${query}` : path;
}

function trimmed(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

export function legacySettingsPath(pathname: string, search = ""): string | null {
  const path = trimmed(pathname);
  const params = new URLSearchParams(search);
  if (path === "/admin/bot" || path.startsWith("/admin/bot/")) {
    const part = params.get("part");
    const section = params.get("section");
    const target =
      (section && BOT_SECTION[section]) || (part && BOT_PART[part]) || "/admin/telegram";
    return withCarried(target, params);
  }
  if (path === "/admin/docflow" || path.startsWith("/admin/docflow/")) {
    return DOCFLOW_TAB[params.get("tab") ?? ""] ?? "/admin/dictionaries?list=doc";
  }
  if (path.startsWith("/admin/company/")) return "/admin/company";
  if (path === "/admin/company") {
    const tab = params.get("tab");
    // `tab=card` — вкладка бокового окна (форма счёта в `Sheet`), а не старая вкладка страницы: не перенаправляем
    if (tab === null || tab === "card") return null;
    return COMPANY_TAB[tab] ?? "/admin/company";
  }
  if (path === "/admin/templates" && params.get("tab") === "quote") return "/admin/sales";
  if (path === "/admin/tickets") return TICKETS_HOME;
  // ЕВ-2а (2026-11-23): шаблоны резолюций — вкладка «Шаблонов»
  if (path === "/admin/resolutions") return withCarried("/admin/templates?tab=resolutions", params);
  // ЕВ-2а (2026-11-23): виды писем и правила отправителей — страница «Почта»
  if (path === "/admin/dictionaries" && MAIL_KINDS_LIST.test(params.get("list") ?? "")) {
    return "/admin/mail#pf-mail-kinds";
  }
  if (path === "/admin/integrations") {
    const card = params.get("card");
    if (card && INTEGRATION_CARD[card]) return INTEGRATION_CARD[card];
  }
  return null;
}
