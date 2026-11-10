import type { AccessRule } from "../types";

/**
 * Реестр настроек (SET-IA; ресёрч `docs/research/2026-11-02-flexibility/4-settings-ia.md` §4.1, §5 M1): один файл данных о
 * каждой странице Настроек — ключ, группа, адрес, право доступа, название, строка описания и слова для поиска на трёх языках.
 * Из него собираются подменю Настроек (`module.ts`), индекс `/admin` с поиском и группа «Настройки» в общем поиске Ctrl K.
 * Название совпадает с `modules:admin.sections.<key>` (тест `settingsRegistry.test.ts`): в меню, на странице, в справке и в
 * поиске — одно и то же. Лимиты текста — §4.2: название до 3 слов, описание до 60 знаков, без названий систем.
 */

export type Lang = "ru" | "uz" | "en";
export type Texts = Readonly<Record<Lang, string>>;

export const SETTINGS_GROUPS = ["people", "company", "channels", "system"] as const;
export type SettingsGroup = (typeof SETTINGS_GROUPS)[number];

/** Названия групп; совпадают с `modules:admin.groups.<group>`. */
export const GROUP_NAMES: Readonly<Record<SettingsGroup, Texts>> = {
  people: { ru: "Сотрудники", uz: "Xodimlar", en: "Employees" },
  company: { ru: "Компания", uz: "Kompaniya", en: "Company" },
  channels: { ru: "Подключения", uz: "Ulanishlar", en: "Connections" },
  system: { ru: "Журнал", uz: "Jurnal", en: "Log" },
};

export interface SettingEntry {
  /** Ключ раздела модуля admin: `modules:admin.sections.<key>`, пункт меню каталога `platform-rbac.yaml` */
  key: string;
  group: SettingsGroup;
  path: string;
  access: AccessRule;
  name: Texts;
  /** Одна строка на карточке индекса, ≤ 60 знаков */
  description: Texts;
  /** Слова, по которым ищут эту настройку (строчные): то, что внутри страницы, и синонимы */
  keywords: Readonly<Record<Lang, readonly string[]>>;
}

const ADMIN: AccessRule = { resource: "admin" };
const COMPANY: AccessRule = { resource: "company.settings" };
/** SIGN-2 (ADR-0024 п. 1): реестр полномочий подписи ведёт держатель раздела `eds.signing.manage` (системная роль администратора). */
const SIGNING: AccessRule = { resource: "eds.signing.manage" };

/** Порядок — порядок групп и пунктов в подменю и на индексе. */
export const SETTINGS: readonly SettingEntry[] = [
  {
    key: "org",
    group: "people",
    path: "/admin/org",
    access: ADMIN,
    name: { ru: "Сотрудники", uz: "Xodimlar", en: "Employees" },
    description: {
      ru: "Приглашения, роли сотрудника, вход и Telegram",
      uz: "Taklif, xodim rollari, kirish va Telegram",
      en: "Invites, employee roles, sign-in and Telegram",
    },
    keywords: {
      ru: ["пригласить", "приглашение", "пароль", "отключить", "пользователи", "люди"],
      uz: ["taklif", "parol", "foydalanuvchilar"],
      en: ["invite", "password", "users", "deactivate", "people"],
    },
  },
  {
    key: "roles",
    group: "people",
    path: "/admin/roles",
    access: ADMIN,
    name: { ru: "Роли и права", uz: "Rollar va huquqlar", en: "Roles & permissions" },
    description: {
      ru: "Что видит и что может каждая роль",
      uz: "Har bir rol nimani ko‘radi va qila oladi",
      en: "What each role can see and do",
    },
    keywords: {
      ru: ["доступ", "матрица", "права", "роль"],
      uz: ["kirish", "huquq", "rol"],
      en: ["access", "matrix", "permission", "role"],
    },
  },
  {
    key: "signing",
    group: "people",
    path: "/admin/signing",
    access: SIGNING,
    name: { ru: "Права подписи", uz: "Imzo huquqlari", en: "Signing authority" },
    description: {
      ru: "Кто и что подписывает: основание, лимит и срок",
      uz: "Kim nimani imzolaydi: asos, limit va muddat",
      en: "Who signs what: basis, limit and term",
    },
    keywords: {
      ru: [
        "подпись",
        "подписант",
        "доверенность",
        "приказ",
        "устав",
        "полномочия",
        "замещение",
        "директор",
        "лимит",
      ],
      uz: ["imzo", "imzolovchi", "ishonchnoma", "buyruq", "nizom", "vakolat", "o‘rinbosar"],
      en: [
        "signature",
        "signatory",
        "power of attorney",
        "order",
        "charter",
        "authority",
        "deputy",
      ],
    },
  },
  {
    key: "company",
    group: "company",
    path: "/admin/company",
    access: COMPANY,
    name: { ru: "Реквизиты и бланк", uz: "Rekvizitlar va blanka", en: "Details & letterhead" },
    description: {
      ru: "Данные компании, логотип и вид документов",
      uz: "Kompaniya ma’lumotlari, logotip va hujjatlar ko‘rinishi",
      en: "Company details, logo and document look",
    },
    keywords: {
      ru: [
        "инн",
        "банк",
        "расчётный счёт",
        "мфо",
        "логотип",
        "бренд",
        "адрес",
        "телефон",
        "печать",
      ],
      uz: ["stir", "bank", "hisob raqam", "logotip", "manzil", "telefon"],
      en: ["tax id", "bank", "account", "logo", "brand", "address", "phone"],
    },
  },
  {
    key: "numbering",
    group: "company",
    path: "/admin/numbering",
    access: COMPANY,
    name: { ru: "Нумерация", uz: "Raqamlash", en: "Numbering" },
    description: {
      ru: "Номера КП, договоров, счетов и актов",
      uz: "TK, shartnoma, hisob va dalolatnoma raqamlari",
      en: "Numbers of quotes, contracts, invoices and acts",
    },
    keywords: {
      ru: ["номер", "префикс", "счётчик", "маска"],
      uz: ["raqam", "prefiks"],
      en: ["number", "prefix", "counter", "mask"],
    },
  },
  {
    key: "taxes",
    group: "company",
    path: "/admin/taxes",
    access: COMPANY,
    name: { ru: "Налоги и валюты", uz: "Soliqlar va valyutalar", en: "Taxes & currencies" },
    description: {
      ru: "НДС, валюта компании и курс",
      uz: "QQS, kompaniya valyutasi va kurs",
      en: "VAT, home currency and exchange rate",
    },
    keywords: {
      ru: ["ндс", "курс", "доллар", "usd", "валюта", "налог"],
      uz: ["qqs", "kurs", "dollar", "valyuta", "soliq"],
      en: ["vat", "rate", "dollar", "usd", "currency", "tax"],
    },
  },
  {
    key: "articles",
    group: "company",
    path: "/admin/articles",
    access: ADMIN,
    name: { ru: "Статьи компании", uz: "Kompaniya maqolalari", en: "Company articles" },
    description: {
      ru: "Инструкции «как у нас принято» для сотрудников",
      uz: "Xodimlar uchun ichki yo‘riqnomalar",
      en: "In-house how-to articles for employees",
    },
    keywords: {
      ru: ["инструкция", "регламент", "помощь", "статья"],
      uz: ["yo‘riqnoma", "yordam", "maqola"],
      en: ["instruction", "policy", "help", "article"],
    },
  },
  {
    key: "telegram",
    group: "channels",
    path: "/admin/telegram",
    access: ADMIN,
    name: { ru: "Telegram", uz: "Telegram", en: "Telegram" },
    description: {
      ru: "Бот: подключение, тексты, ответы и база знаний",
      uz: "Bot: ulanish, matnlar, javoblar va bilimlar bazasi",
      en: "Bot: connection, texts, replies and knowledge base",
    },
    keywords: {
      ru: [
        "бот",
        "токен",
        "тексты бота",
        "шаблоны ответов",
        "база знаний",
        "стоп-слова",
        "конкуренты",
        "квалификация",
      ],
      uz: ["bot", "token", "javob shablonlari", "bilimlar bazasi"],
      en: [
        "bot",
        "token",
        "bot texts",
        "reply templates",
        "knowledge base",
        "stop words",
        "qualification",
      ],
    },
  },
  {
    key: "mail",
    group: "channels",
    path: "/admin/mail",
    access: ADMIN,
    name: { ru: "Почта", uz: "Pochta", en: "Mail" },
    description: {
      ru: "Отправка писем и приём в общий ящик",
      uz: "Xat yuborish va umumiy qutiga qabul",
      en: "Sending mail and the shared inbox",
    },
    keywords: {
      ru: ["email", "smtp", "imap", "письма", "ящик", "отправитель", "спам"],
      uz: ["email", "smtp", "imap", "xat", "quti"],
      en: ["email", "smtp", "imap", "letters", "inbox", "sender", "spam"],
    },
  },
  {
    key: "forms",
    group: "channels",
    path: "/admin/web-forms",
    access: ADMIN,
    name: { ru: "Формы сайта", uz: "Sayt shakllari", en: "Website forms" },
    description: {
      ru: "Заявка с сайта и защита от спама",
      uz: "Saytdan ariza va spamdan himoya",
      en: "Website request form and spam protection",
    },
    keywords: {
      ru: ["сайт", "форма", "заявка", "антиспам"],
      uz: ["sayt", "shakl", "ariza"],
      en: ["website", "form", "request", "anti-spam"],
    },
  },
  {
    key: "dictionaries",
    group: "company",
    path: "/admin/dictionaries",
    // Списки продаж и документов — `admin`, списки расчёта — `company.settings`: страница открыта, если есть любой.
    access: { anyOf: ["admin", "company.settings"] },
    name: { ru: "Справочники", uz: "Ma’lumotnomalar", en: "Lists" },
    description: {
      ru: "Причины отказа, виды писем, валюты, категории",
      uz: "Rad sabablari, xat turlari, valyutalar, toifalar",
      en: "Loss reasons, letter types, currencies, categories",
    },
    keywords: {
      ru: [
        "причины отказа",
        "виды документов",
        "способы получения",
        "страны",
        "единицы",
        "базис поставки",
        "категории",
        "статьи расхода",
        "сделки",
      ],
      uz: [
        "rad sabablari",
        "hujjat turlari",
        "mamlakatlar",
        "birliklar",
        "toifalar",
        "xarajat moddalari",
      ],
      en: [
        "loss reasons",
        "document types",
        "countries",
        "units",
        "delivery basis",
        "categories",
        "charges",
        "deals",
      ],
    },
  },
  {
    key: "resolutions",
    group: "company",
    path: "/admin/resolutions",
    access: ADMIN,
    name: { ru: "Шаблоны резолюций", uz: "Rezolyutsiya shablonlari", en: "Resolution templates" },
    description: {
      ru: "Готовые резолюции для входящих писем",
      uz: "Kiruvchi xatlar uchun tayyor rezolyutsiyalar",
      en: "Ready resolutions for incoming letters",
    },
    keywords: {
      ru: ["резолюция", "поручение", "входящие"],
      uz: ["rezolyutsiya", "topshiriq"],
      en: ["resolution", "instruction", "incoming"],
    },
  },
  {
    key: "templates",
    group: "company",
    path: "/admin/templates",
    access: COMPANY,
    name: { ru: "Шаблоны документов", uz: "Hujjat shablonlari", en: "Document templates" },
    description: {
      ru: "КП, договоры, счета, письма и условия КП",
      uz: "TK, shartnoma, hisob, xatlar va TK shartlari",
      en: "Quotes, contracts, invoices, emails, quote terms",
    },
    keywords: {
      ru: ["шаблон", "письма", "условия кп", "срок действия", "оплата", "просрочка", "напоминание"],
      uz: ["shablon", "xatlar", "tk shartlari", "eslatma"],
      en: ["template", "emails", "quote terms", "validity", "payment", "overdue", "reminder"],
    },
  },
  {
    key: "timing",
    group: "company",
    path: "/admin/timing",
    access: ADMIN,
    name: { ru: "Время и сроки", uz: "Vaqt va muddatlar", en: "Hours & deadlines" },
    description: {
      ru: "Часы работы, срок ответа и передача менеджеру",
      uz: "Ish vaqti, javob muddati va menejerga uzatish",
      en: "Working hours, reply time and handoff to managers",
    },
    keywords: {
      ru: ["sla", "рабочие часы", "выходные", "праздники", "срок ответа", "передача", "эскалация"],
      uz: ["sla", "ish soatlari", "bayramlar", "javob muddati"],
      en: ["sla", "working hours", "holidays", "reply time", "handoff", "escalation"],
    },
  },
  {
    key: "notifications",
    group: "company",
    path: "/admin/notifications",
    access: ADMIN,
    name: { ru: "Уведомления", uz: "Bildirishnomalar", en: "Notifications" },
    description: {
      ru: "Канал команды и оповещения о сбоях",
      uz: "Jamoa kanali va nosozlik haqida xabarlar",
      en: "Team channel and failure alerts",
    },
    keywords: {
      ru: ["канал команды", "оповещения", "сбои", "напоминания", "дежурный"],
      uz: ["jamoa kanali", "ogohlantirish", "nosozlik"],
      en: ["team channel", "alerts", "failures", "reminders", "on duty"],
    },
  },
  {
    key: "integrations",
    group: "channels",
    path: "/admin/integrations",
    access: ADMIN,
    name: { ru: "Сервисы", uz: "Servislar", en: "Services" },
    description: {
      ru: "Состояние сервисов, модели ИИ, хранилище и копии",
      uz: "Servislar holati, SI modellari, ombor va nusxalar",
      en: "Service status, AI models, storage and backups",
    },
    keywords: {
      ru: [
        "модели",
        "ии",
        "бэкап",
        "резервная копия",
        "хранилище",
        "яндекс диск",
        "консоль",
        "состояние",
      ],
      uz: ["modellar", "zaxira nusxa", "ombor", "konsol"],
      en: ["models", "ai", "backup", "storage", "console", "status"],
    },
  },
  {
    key: "spend",
    group: "channels",
    path: "/admin/ai-spend",
    access: ADMIN,
    name: { ru: "Расходы на ИИ", uz: "SI xarajatlari", en: "AI spend" },
    description: {
      ru: "Расходы, дневной лимит и защита данных для ИИ",
      uz: "Xarajatlar, kunlik limit va SI uchun ma’lumotlar himoyasi",
      en: "Costs, daily limit and data protection for AI",
    },
    keywords: {
      ru: [
        "бюджет",
        "лимит",
        "деньги",
        "стоимость",
        "помощник",
        "защита данных",
        "персональные данные",
        "паспорт",
        "политика",
        "сканы",
        "деловая",
        "строгая",
      ],
      uz: ["byudjet", "limit", "narx", "ma’lumotlar himoyasi", "pasport", "siyosat", "skan"],
      en: [
        "budget",
        "limit",
        "cost",
        "assistant",
        "data protection",
        "personal data",
        "passport",
        "policy",
        "scans",
      ],
    },
  },
  {
    key: "audit",
    group: "system",
    path: "/admin/audit",
    access: ADMIN,
    name: { ru: "История", uz: "Tarix", en: "History" },
    description: {
      ru: "Кто, что и когда изменил",
      uz: "Kim, nimani va qachon o‘zgartirgan",
      en: "Who changed what and when",
    },
    keywords: {
      ru: ["аудит", "лог", "история", "изменения"],
      uz: ["audit", "tarix", "o‘zgarishlar"],
      en: ["audit", "log", "history", "changes"],
    },
  },
  {
    key: "exports",
    group: "system",
    path: "/admin/exports",
    access: ADMIN,
    name: { ru: "Выгрузки", uz: "Eksport", en: "Exports" },
    description: {
      ru: "Лиды, клиенты и сделки в файл для Excel",
      uz: "Lidlar, mijozlar va bitimlar Excel fayliga",
      en: "Leads, clients and deals to a file for Excel",
    },
    keywords: {
      ru: ["экспорт", "csv", "excel", "выгрузить"],
      uz: ["eksport", "csv", "excel"],
      en: ["export", "csv", "excel", "download"],
    },
  },
  {
    key: "bus",
    group: "system",
    path: "/admin/bus",
    access: { resource: "admin", level: "full" },
    name: { ru: "Обмен между системами", uz: "Tizimlararo almashinuv", en: "System exchange" },
    description: {
      ru: "Доставка событий между частями платформы",
      uz: "Platforma qismlari orasida hodisalar yetkazilishi",
      en: "Event delivery between parts of the platform",
    },
    keywords: {
      ru: ["шина", "события", "доставка", "повторить"],
      uz: ["hodisalar", "yetkazish"],
      en: ["bus", "events", "delivery", "retry"],
    },
  },
];

export function settingByKey(key: string): SettingEntry | undefined {
  return SETTINGS.find((entry) => entry.key === key);
}

/** «Ё» и регистр не различаем: «расчётный» находится по «расчетный». */
function norm(text: string): string {
  return text.toLocaleLowerCase().replace(/ё/g, "е");
}

function words(text: string): string[] {
  return norm(text)
    .split(/[\s,·.«»"()/–—-]+/)
    .filter(Boolean);
}

/** Запрос короче двух знаков ничего не ищет. */
export const MIN_SETTINGS_QUERY = 2;

export interface SettingHit {
  entry: SettingEntry;
  /** Чем найдено, если не названием: слово из `keywords` на языке интерфейса или любом другом */
  matchedBy?: string;
}

/**
 * Поиск по реестру (HubSpot, Google Admin: по названию, описанию и ключевым словам). Каждое слово запроса должно быть началом
 * слова в названии, описании или ключевых словах на любом из трёх языков (сотрудник ищет «mail» и в русском интерфейсе).
 * Выше — совпадения по названию. `allowed` — права: недоступное не находится.
 */
export function searchSettings(
  query: string,
  lang: Lang,
  allowed: (entry: SettingEntry) => boolean = () => true,
): SettingHit[] {
  const q = words(query);
  if (norm(query).trim().length < MIN_SETTINGS_QUERY || q.length === 0) return [];
  const hits: { hit: SettingHit; rank: number }[] = [];
  for (const entry of SETTINGS) {
    if (!allowed(entry)) continue;
    const langs: Lang[] = [lang, ...(["ru", "uz", "en"] as const).filter((l) => l !== lang)];
    const nameWords = langs.flatMap((l) => words(entry.name[l]));
    const descWords = langs.flatMap((l) => words(entry.description[l]));
    const phrases = langs.flatMap((l) => entry.keywords[l]);
    const keywordWords = phrases.flatMap(words);
    const pool = [...nameWords, ...descWords, ...keywordWords];
    if (!q.every((part) => pool.some((word) => word.startsWith(part)))) continue;
    const byName = q.every((part) => nameWords.some((word) => word.startsWith(part)));
    if (byName) {
      hits.push({ hit: { entry }, rank: 0 });
      continue;
    }
    const phrase = phrases.find((p) => q.every((part) => words(p).some((w) => w.startsWith(part))));
    const byDescription = q.every((part) => descWords.some((word) => word.startsWith(part)));
    hits.push({
      hit: phrase && !byDescription ? { entry, matchedBy: phrase } : { entry },
      rank: byDescription ? 1 : 2,
    });
  }
  return hits.sort((a, b) => a.rank - b.rank).map(({ hit }) => hit);
}

export function langOf(language: string | undefined): Lang {
  const base = (language ?? "ru").slice(0, 2);
  return base === "uz" || base === "en" ? base : "ru";
}
