import type { ModuleCode, ObjectKind } from "../shared/api/generated/model";
// Односторонняя зависимость: `registry` (карта разделов) про мост не знает, поэтому цикла `bridge` ↔ `registry` нет.
import { matchSection } from "./registry";

/**
 * Мост в старые экраны (W15-H1, UX-оценка P0-2): пока раздел Платформы — заглушка, здесь записано, где эта работа
 * делается сейчас и когда появится в Платформе. Запись есть ⇒ раздел ещё заглушка: у него нет бейджа без подсказки и нет
 * бокового окна. Когда раздел получает настоящий экран (волна 16 и дальше), запись удаляют, а ключ добавляют в
 * `NATIVE_SECTIONS` — тест `bridge.test.ts` требует для каждого раздела одно из двух.
 *
 * Тексты — пространство `bridge` (ru/uz/en): `where.<ключ>` — раздел в старой системе, `who.<ключ>` — кто делает работу
 * вне интерфейса. Названия разделов старых систем — как их видит сотрудник в старом интерфейсе.
 */
export type LegacySystem = "crm" | "erp";

/** Когда раздел появится в Платформе: «в ближайшем обновлении» — волна 16 (D1), всё остальное — «к пилоту». */
export type When = "soon" | "pilot";

export interface LegacyTarget {
  system: LegacySystem;
  /** Адрес в старой системе: CRM — путь (`/inbox`), ERP — хэш-маршрут (`#crm-deals`); добавляется к её публичному адресу */
  path: string;
  /** Ключ `bridge:where.*` */
  where: string;
  /** Карточка объекта: путь в старой системе по номеру из адреса Платформы; не подошёл номер — `path` */
  object?: (objectId: string) => string | undefined;
}

export interface BridgeEntry {
  /** Где работа делается сейчас; без поля — в интерфейсе её нет, см. `who` */
  legacy?: LegacyTarget;
  /** Ключ `bridge:who.*`: кто и как делает работу вне интерфейса (когда `legacy` нет) */
  who?: string;
  /** Работа уже есть в Платформе в другом разделе (Каналы связи — в Admin) */
  internal?: { to: string; resource: string; section: string };
  when: When;
  /**
   * Число из бейджа меню видно и в старой системе (счётчик считает тот же бэкенд): бейдж остаётся с подсказкой «в старой
   * CRM: N». Без флага бейдж у заглушки не показывается — число нечем подтвердить, а открыть за ним нечего.
   */
  legacyCount?: boolean;
  /** Что открывается по прямой ссылке на карточку (`/eds/inbox/ВХ-104%2F26`): подпись типа берётся из `shell:search.kind` */
  objectKind?: ObjectKind;
}

const crm = (path: string, where: string, object?: LegacyTarget["object"]): LegacyTarget => ({
  system: "crm",
  path,
  where,
  ...(object ? { object } : {}),
});
const erp = (path: string, where: string, object?: LegacyTarget["object"]): LegacyTarget => ({
  system: "erp",
  path,
  where,
  ...(object ? { object } : {}),
});

const numericPath = (prefix: string) => (objectId: string) =>
  /^\d+$/.test(objectId) ? `${prefix}${objectId}` : undefined;

/** Ключ — `<модуль>.<раздел>`, как в `module.ts` модуля. */
export const BRIDGE: Readonly<Record<string, BridgeEntry>> = {
  "dashboard.projects": {
    legacy: erp("#crm-deals", "erpDeals"),
    when: "pilot",
    legacyCount: true,
  },
  "dashboard.summary": { legacy: crm("/dashboard", "crmDashboard"), when: "pilot" },

  // «Лиды» и «Клиенты» — настоящие экраны (D1-2b), записей моста у них нет.
  "crm.requests": {
    legacy: erp("#crm-deals", "erpDeals", numericPath("#request-detail/")),
    when: "pilot",
    objectKind: "request",
  },
  "crm.channels": {
    // Бот подключается в «Настройки · Telegram-бот» (W15-H4), а не в «Подключениях»
    internal: { to: "/admin/bot", resource: "admin", section: "bot" },
    when: "pilot",
  },

  "eds.outbox": {
    legacy: erp("#crm-quotes", "erpQuotes"),
    when: "pilot",
    objectKind: "quote",
  },
  "eds.projects": {
    legacy: erp("#crm-deals", "erpDeals", numericPath("#request-detail/")),
    when: "pilot",
    objectKind: "project",
  },
  // «Все документы» и «Создать документ» (D1-5), «КП на одобрение» и «На согласовании» (D1-4) — настоящие экраны, записей моста у них нет.
  "eds.payments": {
    legacy: erp("#payments", "erpPayments"),
    when: "pilot",
    objectKind: "invoice",
  },

  "erp.stock": { legacy: erp("#my-products", "erpStock"), when: "pilot" },
  "erp.catalog": { legacy: erp("#catalog-reference", "erpCatalog"), when: "pilot" },
  "erp.docs": { legacy: erp("#company-files", "erpFiles"), when: "pilot" },

  "chats.all": { who: "chats", when: "pilot", objectKind: "chat" },
  "chats.internal": { who: "chats", when: "pilot", objectKind: "chat" },
  "chats.external": { legacy: crm("/inbox", "crmInbox"), when: "pilot", objectKind: "chat" },
  "chats.contacts": { who: "chats", when: "pilot" },
};

/** Разделы с настоящим экраном: моста у них нет. Новый настоящий экран — сюда, а запись из `BRIDGE` — удалить. */
export const NATIVE_SECTIONS: readonly string[] = [
  "dashboard.queue",
  "crm.messages",
  "crm.leads",
  "crm.clients",
  "crm.kb",
  "eds.documents",
  "eds.new",
  "eds.inbox",
  "erp.requests",
  "erp.calc",
  "eds.drafts",
  "eds.approvals",
  "admin.roles",
  "admin.org",
  "admin.integrations",
  "admin.bus",
  "admin.setup",
  "admin.company",
  "admin.bot",
  "admin.audit",
  "admin.tickets",
];

/** Главные действия модулей без экрана (кнопка внизу подменю неактивна): когда появятся. Остальных модулей это не касается. */
export const MODULE_ACTION_WHEN: Readonly<Partial<Record<ModuleCode, When>>> = {
  eds: "soon",
  erp: "pilot",
  chats: "pilot",
};

export function bridgeKey(module: string, section: string): string {
  return `${module}.${section}`;
}

/** Запись моста раздела-заглушки; `undefined` — у раздела настоящий экран (или записи нет). */
export function bridgeEntry(module: string, section: string): BridgeEntry | undefined {
  return BRIDGE[bridgeKey(module, section)];
}

/** Раздел всё ещё заглушка: в `BRIDGE` есть запись. */
export function isStubSection(module: string, section: string): boolean {
  return bridgeEntry(module, section) !== undefined;
}

/** Параметры адреса, в которых лежит номер объекта, когда у раздела нет `:id` (`/crm/leads?lead=L-2041`). */
const OBJECT_PARAMS = [
  "lead",
  "request",
  "client",
  "project",
  "letter",
  "quote",
  "memo",
  "invoice",
];

/** Номер объекта из адреса: `:id` карточки или первый из `?lead=`, `?request=`… Для списка — `undefined`. */
export function objectIdOf(
  match: { objectId?: string | undefined },
  search: string,
): string | undefined {
  if (match.objectId !== undefined) return match.objectId;
  const params = new URLSearchParams(search);
  for (const name of OBJECT_PARAMS) {
    const value = params.get(name);
    if (value) return value;
  }
  return undefined;
}

/**
 * Полный адрес кнопки «Открыть в …»: публичный адрес старой системы + путь; для карточки — прямой путь, если номер
 * объекта подходит под старый маршрут. Адреса нет — `undefined` (кнопки не будет).
 */
export function legacyHref(
  target: LegacyTarget,
  baseUrl: string | null | undefined,
  objectId?: string,
): string | undefined {
  if (!baseUrl) return undefined;
  const path = (objectId !== undefined ? target.object?.(objectId) : undefined) ?? target.path;
  // ERP — хэш-маршруты SPA (`#crm-deals`): корень со слэшем, дальше хэш.
  return target.system === "erp" ? `${baseUrl}/${path}` : `${baseUrl}${path}`;
}

/** Заголовок карточки: «Письмо ВХ-104/26»; номер уже с префиксом типа («КП-2026/118») — без повтора. */
export function objectTitle(kindLabel: string | undefined, number: string): string {
  if (!kindLabel) return number;
  return number.toLocaleLowerCase().startsWith(kindLabel.toLocaleLowerCase())
    ? number
    : `${kindLabel} ${number}`;
}

export interface RouteTarget {
  module: string;
  section: string;
  /** Номер объекта из адреса (`/eds/drafts/КП-2026%2F118`, `?lead=L-2041`); для списка — `undefined` */
  objectId?: string | undefined;
  /** Запись моста, если раздел ещё заглушка */
  entry?: BridgeEntry | undefined;
}

/** Раздел и объект по адресу вида `/eds/drafts/КП-2026%2F118?panel=open`; адрес не из карты Платформы — `undefined`. */
export function routeTarget(path: string): RouteTarget | undefined {
  const [pathname = "", search = ""] = path.split("?");
  const match = matchSection(pathname, search);
  if (!match) return undefined;
  return {
    module: match.module.code,
    section: match.section.key,
    objectId: objectIdOf(match, search),
    entry: bridgeEntry(match.module.code, match.section.key),
  };
}

/**
 * Можно ли выполнить работу по адресу в самой Платформе: у раздела есть настоящий экран, то есть записи моста нет.
 * Одна функция на «Мои задачи», поиск и колокольчик: волна 16 снимает мост, добавляя раздел в `NATIVE_SECTIONS` и
 * удаляя его запись из `BRIDGE`, — и все три места сами начинают открывать объект в боковом окне. Адрес не из карты
 * (404 внутри каркаса) считается исполнимым: ссылку не прячем.
 */
export function isActionable(path: string): boolean {
  return routeTarget(path)?.entry === undefined;
}
