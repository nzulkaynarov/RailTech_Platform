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

export const SETTINGS_GROUPS = ["people", "company", "rules", "channels", "journal"] as const;
export type SettingsGroup = (typeof SETTINGS_GROUPS)[number];

/** Названия групп; совпадают с `modules:admin.groups.<group>`. */
export const GROUP_NAMES: Readonly<Record<SettingsGroup, Texts>> = {
  people: { ru: "Люди и доступ", uz: "Odamlar va kiriş", en: "People & access" },
  company: { ru: "Компания", uz: "Kompaniya", en: "Company" },
  rules: { ru: "Правила работы", uz: "Iş qoidalari", en: "Work rules" },
  channels: {
    ru: "Каналы и подключения",
    uz: "Kanallar va ulanişlar",
    en: "Channels & connections",
  },
  journal: { ru: "Журнал", uz: "Jurnal", en: "Log" },
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
/** ЕВ-2а: страницы фундамента (каналы, подключения, ИИ, выгрузки) — только администратор; директору они не показываются. */
const SYSTEM: AccessRule = { resource: "admin.system" };
/** SIGN-2 (ADR-0024 п. 1): реестр полномочий подписи ведёт держатель раздела `eds.signing.manage` (системная роль администратора). */
const SIGNING: AccessRule = { resource: "eds.signing.manage" };

/** Порядок — порядок групп и пунктов в подменю и на индексе. */
export const SETTINGS: readonly SettingEntry[] = [
  {
    key: "org",
    group: "people",
    path: "/admin/org",
    access: ADMIN,
    name: {
      ru: "Сотрудники и возможности",
      uz: "Xodimlar va imkoniyatlar",
      en: "Staff and capabilities",
    },
    description: {
      ru: "Кто что может, приглашения, роли, вход и Telegram",
      uz: "Kim nimani qila oladi, taklif, rollar, kiriş, Telegram",
      en: "Who can do what, invites, roles, sign-in, Telegram",
    },
    keywords: {
      ru: ["пригласить", "приглашение", "пароль", "отключить", "пользователи", "люди"],
      uz: ["taklif", "parol", "foydalanuvçilar"],
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
      uz: "Har bir rol nimani köradi va qila oladi",
      en: "What each role can see and do",
    },
    keywords: {
      ru: ["доступ", "матрица", "права", "роль"],
      uz: ["kiriş", "huquq", "rol"],
      en: ["access", "matrix", "permission", "role"],
    },
  },
  {
    key: "zones",
    group: "people",
    path: "/admin/zones",
    access: ADMIN,
    name: { ru: "Зоны ответственности", uz: "Masʼuliyat zonalari", en: "Responsibility zones" },
    description: {
      ru: "Ответственный, замещающий и куратор по каждой зоне",
      uz: "Har bir zona uçun masʼul, örinbosar va kurator",
      en: "Responsible, deputy and curator for each zone",
    },
    keywords: {
      ru: [
        "зона",
        "ответственный",
        "куратор",
        "замещающий",
        "приказ",
        "финансы",
        "право",
        "снабжение",
      ],
      uz: ["zona", "masʼul", "kurator", "örinbosar", "buyruq", "moliya", "huquq"],
      en: ["zone", "responsible", "owner", "curator", "deputy", "order", "finance", "legal"],
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
      uz: ["imzo", "imzolovçi", "işonçnoma", "buyruq", "nizom", "vakolat", "örinbosar"],
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
      ru: "Данные и контакты компании, логотип и вид документов",
      uz: "Kompaniya maʼlumotlari, kontaktlar, logotip va blanka",
      en: "Company details, contacts, logo and document look",
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
        "поддержка",
        "адрес поддержки",
      ],
      uz: ["stir", "bank", "hisob raqam", "logotip", "manzil", "telefon", "yordam"],
      en: ["tax id", "bank", "account", "logo", "brand", "address", "phone", "support"],
    },
  },
  {
    key: "numbering",
    group: "company",
    path: "/admin/numbering",
    access: COMPANY,
    name: { ru: "Нумерация", uz: "Raqamlaş", en: "Numbering" },
    description: {
      ru: "Номера КП, договоров, счетов и актов",
      uz: "TT, şartnoma, hisob va dalolatnoma raqamlari",
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
      uz: "Xodimlar uçun içki yöriqnomalar",
      en: "In-house how-to articles for employees",
    },
    keywords: {
      ru: ["инструкция", "регламент", "помощь", "статья"],
      uz: ["yöriqnoma", "yordam", "maqola"],
      en: ["instruction", "policy", "help", "article"],
    },
  },
  {
    key: "sales",
    group: "rules",
    path: "/admin/sales",
    access: COMPANY,
    name: { ru: "Продажи", uz: "Sotuvlar", en: "Sales" },
    description: {
      ru: "Условия нового КП: срок, оплата, гарантия, маржа",
      uz: "Yangi TT şartları: muddat, tölov, kafolat, marja",
      en: "New quote terms: validity, payment, warranty, margin",
    },
    keywords: {
      ru: [
        "условия кп",
        "срок действия",
        "оплата",
        "отсрочка",
        "гарантия",
        "маржа",
        "базис поставки",
        "каталог",
        "свежесть цен поставщиков",
        "цена в каталоге",
        "порог карточки",
      ],
      uz: ["tt şartları", "amal qiliş muddati", "tölov", "kafolat", "marja", "katalog"],
      en: [
        "quote terms",
        "validity",
        "payment",
        "warranty",
        "margin",
        "delivery basis",
        "catalog",
        "catalog price",
      ],
    },
  },
  {
    key: "legal",
    group: "company",
    path: "/admin/legal",
    access: COMPANY,
    name: { ru: "Оферта и политика", uz: "Oferta va siyosat", en: "Offer and policy" },
    description: {
      ru: "Что клиенты принимают при входе в кабинет и кто принял",
      uz: "Kabinetga kirişda qabul qilinadigan matnlar va qabullar",
      en: "What clients accept on sign-in, and who accepted",
    },
    keywords: {
      ru: [
        "оферта",
        "политика",
        "персональные данные",
        "согласие",
        "акцепт",
        "условия",
        "договор",
        "кабинет",
      ],
      uz: [
        "oferta",
        "siyosat",
        "şaxsga doir maʼlumotlar",
        "rozilik",
        "aksept",
        "şartlar",
        "kabinet",
      ],
      en: [
        "offer",
        "terms",
        "privacy",
        "policy",
        "personal data",
        "consent",
        "acceptance",
        "cabinet",
      ],
    },
  },
  {
    key: "timing",
    group: "rules",
    path: "/admin/timing",
    access: ADMIN,
    name: { ru: "Время и сроки", uz: "Vaqt va muddatlar", en: "Hours & deadlines" },
    description: {
      ru: "Часы работы, праздники и срок первого ответа",
      uz: "Iş vaqti, bayramlar va birinçi javob muddati",
      en: "Working hours, holidays and first reply time",
    },
    keywords: {
      ru: [
        "sla",
        "рабочие часы",
        "выходные",
        "праздники",
        "срок ответа",
        "срок первого ответа",
        "напоминание менеджеру",
      ],
      uz: ["sla", "iş soatlari", "bayramlar", "javob muddati", "birinçi javob"],
      en: ["sla", "working hours", "holidays", "reply time", "first reply", "manager reminder"],
    },
  },
  {
    key: "dictionaries",
    group: "rules",
    path: "/admin/dictionaries",
    // Списки продаж и документов — `admin`, списки расчёта — `company.settings`: страница открыта, если есть любой.
    access: { anyOf: ["admin", "company.settings"] },
    name: { ru: "Справочники", uz: "Maʼlumotnomalar", en: "Lists" },
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
    key: "templates",
    group: "rules",
    path: "/admin/templates",
    access: COMPANY,
    name: { ru: "Шаблоны", uz: "Şablonlar", en: "Templates" },
    description: {
      ru: "КП, договоры, счета, акты, письма и резолюции",
      uz: "TT, şartnoma, hisob, dalolatnoma, xatlar va rezolyutsiyalar",
      en: "Quotes, contracts, invoices, acts, letters and resolutions",
    },
    keywords: {
      ru: ["шаблон", "письма", "бланк", "резолюция", "поручение", "входящие"],
      uz: ["şablon", "xatlar", "blank", "rezolyutsiya", "topşiriq"],
      en: ["template", "letters", "letterhead", "resolution", "instruction", "incoming"],
    },
  },
  {
    key: "notifications",
    group: "rules",
    path: "/admin/notifications",
    access: ADMIN,
    name: { ru: "Уведомления", uz: "Bildirişnomalar", en: "Notifications" },
    description: {
      ru: "Напоминания и оповещения о сбоях",
      uz: "Eslatmalar va nosozlik haqida xabarlar",
      en: "Reminders and failure alerts",
    },
    keywords: {
      ru: [
        "канал команды",
        "оповещения",
        "сбои",
        "напоминания",
        "дежурный",
        "просрочка",
        "напоминание о счёте",
        "акт",
      ],
      uz: [
        "jamoa kanali",
        "ogohlantiriş",
        "nosozlik",
        "muddati ötgan",
        "hisob eslatmasi",
        "dalolatnoma",
      ],
      en: [
        "team channel",
        "alerts",
        "failures",
        "reminders",
        "on duty",
        "overdue",
        "invoice reminder",
        "act",
      ],
    },
  },
  {
    key: "telegram",
    group: "channels",
    path: "/admin/telegram",
    access: SYSTEM,
    name: { ru: "Telegram", uz: "Telegram", en: "Telegram" },
    description: {
      ru: "Бот: подключение, канал команды, тексты и передача",
      uz: "Bot: ulaniş, jamoa kanali, matnlar va topşiriş",
      en: "Bot: connection, team channel, texts and handoff",
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
        "канал команды",
        "передача менеджеру",
        "порог передачи",
      ],
      uz: ["bot", "token", "javob şablonlari", "bilimlar bazasi", "jamoa kanali", "topşiriş"],
      en: [
        "bot",
        "token",
        "bot texts",
        "reply templates",
        "knowledge base",
        "stop words",
        "qualification",
        "team channel",
        "handoff",
      ],
    },
  },
  {
    key: "mail",
    group: "channels",
    path: "/admin/mail",
    access: SYSTEM,
    name: { ru: "Почта", uz: "Poçta", en: "Mail" },
    description: {
      ru: "Отправка, общий ящик, виды писем и отправители",
      uz: "Yuboriş, umumiy quti, xat turlari va jönatuvçilar",
      en: "Sending, shared inbox, letter kinds and senders",
    },
    keywords: {
      ru: [
        "email",
        "smtp",
        "imap",
        "письма",
        "ящик",
        "отправитель",
        "спам",
        "виды писем",
        "типы писем",
      ],
      uz: ["email", "smtp", "imap", "xat", "quti", "xat turlari"],
      en: ["email", "smtp", "imap", "letters", "inbox", "sender", "spam", "letter kinds"],
    },
  },
  {
    key: "forms",
    group: "channels",
    path: "/admin/web-forms",
    access: SYSTEM,
    name: { ru: "Формы сайта", uz: "Sayt şakllari", en: "Website forms" },
    description: {
      ru: "Заявка с сайта и защита от спама",
      uz: "Saytdan ariza va spamdan himoya",
      en: "Website request form and spam protection",
    },
    keywords: {
      ru: ["сайт", "форма", "заявка", "антиспам"],
      uz: ["sayt", "şakl", "ariza"],
      en: ["website", "form", "request", "anti-spam"],
    },
  },
  {
    key: "integrations",
    group: "channels",
    path: "/admin/integrations",
    access: SYSTEM,
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
    access: SYSTEM,
    name: { ru: "ИИ", uz: "SI", en: "AI" },
    description: {
      ru: "Расходы, дневной лимит и защита данных для ИИ",
      uz: "Xarajatlar, kunlik limit va SI uçun maʼlumotlar himoyasi",
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
      uz: ["byudjet", "limit", "narx", "maʼlumotlar himoyasi", "pasport", "siyosat", "skan"],
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
    group: "journal",
    path: "/admin/audit",
    access: ADMIN,
    name: { ru: "История", uz: "Tarix", en: "History" },
    description: {
      ru: "Действия людей и обмен между системами",
      uz: "Odamlar harakatlari va tizimlararo almaşinuv",
      en: "People’s actions and exchange between systems",
    },
    keywords: {
      ru: ["аудит", "лог", "история", "изменения", "шина", "события", "доставка", "повторить"],
      uz: ["audit", "tarix", "özgarişlar", "hodisalar", "yetkaziş"],
      en: ["audit", "log", "history", "changes", "bus", "events", "delivery", "retry"],
    },
  },
  {
    key: "exports",
    group: "journal",
    path: "/admin/exports",
    access: SYSTEM,
    name: { ru: "Выгрузки", uz: "Eksport", en: "Exports" },
    description: {
      ru: "Сделки в файл для Excel, без контактов",
      uz: "Bitimlar Excel fayliga, kontaktlarsiz",
      en: "Deals to a file for Excel, no contact details",
    },
    keywords: {
      ru: ["экспорт", "csv", "excel", "выгрузить"],
      uz: ["eksport", "csv", "excel"],
      en: ["export", "csv", "excel", "download"],
    },
  },
];

/** Страницы без пункта в меню, которые показываются внутри группы своей родительской страницы. */
const PARENT_PAGE: Readonly<Record<string, string>> = { "/admin/bus": "audit" };

/** Страница Настроек, на которой стоит адрес (с учётом скрытых страниц-видов). */
export function entryAt(pathname: string): SettingEntry | undefined {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  const parent = PARENT_PAGE[path];
  return SETTINGS.find(
    (entry) => entry.key === parent || path === entry.path || path.startsWith(`${entry.path}/`),
  );
}

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

/** Порядок страниц внутри групп Настроек по макету 54; остальные — как в реестре. */
const MENU_ORDER = [
  "sales",
  "timing",
  "notifications",
  "templates",
  "dictionaries",
  "mail",
  "telegram",
  "forms",
  "spend",
  "integrations",
];

/**
 * Страницы Настроек в порядке единого меню: группы по `SETTINGS_GROUPS`, внутри группы — по макету 54. Одна функция для меню,
 * всплывающего меню значка и выбора над страницей — порядок везде один.
 */
export function settingsInMenuOrder(entries: readonly SettingEntry[]): SettingEntry[] {
  const rank = (key: string) => MENU_ORDER.indexOf(key);
  return SETTINGS_GROUPS.flatMap((group) =>
    entries.filter((entry) => entry.group === group).sort((a, b) => rank(a.key) - rank(b.key)),
  );
}
