import type { ModuleCode } from "../shared/api/generated/model";
import { MODULES, type SectionMatch } from "./registry";
import { SETTINGS, type SettingsGroup } from "./admin/settingsRegistry";
import type { SectionConfig } from "./types";

/**
 * Меню Платформы (docs/product/NAVIGATION.md): что видит сотрудник в рейле и подменю. Разделы, адреса и права остаются
 * в `module.ts`: меню только раскладывает их по пунктам, поэтому раздел может стоять не в своём модуле. Подпись пункта —
 * `modules:<module>.nav.<key>`.
 */
export interface NavTarget {
  /** Раздел `<module>.<key>`: его право решает, виден ли пункт */
  section: string;
  /** Адрес, если он не совпадает с адресом раздела */
  to?: string;
}

export interface NavTab {
  key: string;
  /** Ключ подписи, если он не `modules:<module>.nav.<key>` */
  label?: string;
  targets: readonly NavTarget[];
  /** Разделы без своей вкладки, которые подсвечивают эту */
  also?: readonly string[];
  /** Разделы, карточка объекта которых относится к этой вкладке, даже если сам список живёт в другой */
  objects?: readonly string[];
}

export interface NavItem {
  key: string;
  /** Первый доступный сотруднику адрес — куда ведёт пункт */
  targets: readonly NavTarget[];
  /** Разделы без своего пункта, которые подсвечивают этот; их счётчики входят в бейдж */
  also?: readonly string[];
  /** Вкладки над экраном: разные объекты одного пункта */
  tabs?: readonly NavTab[];
}

/**
 * Пункт Настроек: открывает первую доступную страницу группы, остальные страницы группы — вкладками над ней (как «Каталог»).
 * Индекс `/admin` с поиском и чек-листом первого запуска остаётся по своему адресу.
 */
function settingsItem(
  key: string,
  group: SettingsGroup,
  skip: readonly string[] = [],
  also?: readonly string[],
): NavItem {
  const entries = SETTINGS.filter((entry) => entry.group === group && !skip.includes(entry.key));
  const targets = entries.map((entry): NavTarget => ({ section: `admin.${entry.key}` }));
  return {
    key,
    targets,
    ...(also ? { also } : {}),
    tabs: entries.map((entry) => ({
      key: entry.key,
      label: `modules:admin.sections.${entry.key}`,
      targets: [{ section: `admin.${entry.key}` }],
    })),
  };
}

const docs = (box: string): NavTarget => ({
  section: "eds.documents",
  to: `/eds/documents?box=${box}`,
});

const REQUESTS: readonly NavTarget[] = [{ section: "erp.requests" }, { section: "crm.requests" }];
const PURCHASES: readonly NavTarget[] = [{ section: "erp.stock", to: "/erp/stock?view=orders" }];
const INVOICES: readonly NavTarget[] = [{ section: "eds.payments" }];
const PAY_REQUESTS: readonly NavTarget[] = [
  { section: "eds.payments", to: "/eds/payments?show=memos" },
];
const PRODUCTS: readonly NavTarget[] = [{ section: "erp.catalog" }];
const STOCK: readonly NavTarget[] = [{ section: "erp.stock" }];
const TECH_DOCS: readonly NavTarget[] = [{ section: "erp.docs" }];

export const NAVIGATION: Readonly<Record<ModuleCode, readonly NavItem[]>> = {
  dashboard: [
    { key: "queue", targets: [{ section: "dashboard.queue" }], also: ["eds.tasks", "eds.mymail"] },
    { key: "projects", targets: [{ section: "eds.projects" }], also: ["dashboard.projects"] },
    { key: "summary", targets: [{ section: "dashboard.summary" }] },
  ],
  crm: [
    { key: "leads", targets: [{ section: "crm.leads" }], also: ["crm.messages"] },
    { key: "clients", targets: [{ section: "crm.clients" }] },
    { key: "mail", targets: [{ section: "eds.mail" }] },
    { key: "kb", targets: [{ section: "crm.kb" }] },
  ],
  eds: [
    { key: "inbox", targets: [{ section: "eds.inbox" }], also: ["eds.register"] },
    { key: "outbox", targets: [docs("outgoing")], also: ["eds.outbox", "eds.drafts"] },
    { key: "internal", targets: [docs("internal")], also: ["eds.approvals"] },
    { key: "archive", targets: [docs("archive")] },
    { key: "templates", targets: [{ section: "admin.templates" }] },
  ],
  erp: [
    {
      key: "requests",
      targets: REQUESTS,
      also: ["erp.calc"],
      tabs: [
        { key: "sales", targets: REQUESTS, also: ["erp.calc"] },
        { key: "purchases", targets: PURCHASES, objects: ["erp.stock"] },
      ],
    },
    {
      key: "catalog",
      targets: [...PRODUCTS, ...STOCK, ...TECH_DOCS],
      tabs: [
        { key: "products", targets: PRODUCTS },
        { key: "stock", targets: STOCK },
        { key: "docs", targets: TECH_DOCS },
      ],
    },
    {
      key: "finance",
      targets: INVOICES,
      tabs: [
        { key: "invoices", targets: INVOICES },
        { key: "memos", targets: PAY_REQUESTS },
      ],
    },
  ],
  chats: [
    { key: "calendar", targets: [{ section: "chats.calendar" }] },
    {
      key: "chats",
      targets: [{ section: "chats.all" }],
      also: ["chats.internal", "chats.external"],
    },
    { key: "people", targets: [{ section: "chats.contacts" }] },
  ],
  admin: [
    settingsItem("people", "people"),
    settingsItem("company", "company", ["templates"]),
    settingsItem("channels", "channels", [], ["crm.channels"]),
    settingsItem("system", "system"),
  ],
};

export interface ResolvedTab {
  key: string;
  to: string;
  label?: string;
}

export interface ResolvedItem {
  item: NavItem;
  to: string;
  tabs: readonly ResolvedTab[];
}

export interface NavHit {
  module: ModuleCode;
  item: NavItem;
  tab?: NavTab | undefined;
}

type CanSee = (section: SectionConfig) => boolean;

function sectionOf(ref: string): SectionConfig | undefined {
  const [code, key] = ref.split(".");
  return MODULES.find((m) => m.code === code)?.sections.find((s) => s.key === key);
}

function pathOf(target: NavTarget): string | undefined {
  return target.to ?? sectionOf(target.section)?.path;
}

function firstPath(targets: readonly NavTarget[], can: CanSee): string | undefined {
  for (const target of targets) {
    const section = sectionOf(target.section);
    if (section && can(section)) return pathOf(target);
  }
  return undefined;
}

/** Пункты подменю модуля, которые доступны сотруднику. */
export function visibleItems(code: ModuleCode, can: CanSee): readonly ResolvedItem[] {
  return NAVIGATION[code].flatMap((item) => {
    const to = firstPath(item.targets, can);
    if (to === undefined) return [];
    const tabs = (item.tabs ?? []).flatMap((tab) => {
      const tabTo = firstPath(tab.targets, can);
      if (tabTo === undefined) return [];
      return [
        tab.label ? { key: tab.key, to: tabTo, label: tab.label } : { key: tab.key, to: tabTo },
      ];
    });
    return [{ item, to, tabs }];
  });
}

function hasQuery(want: string, pathname: string, search: string): boolean {
  const [path = "", query = ""] = want.split("?");
  if (path !== pathname || query === "") return false;
  const have = new URLSearchParams(search);
  for (const [key, value] of new URLSearchParams(query)) if (have.get(key) !== value) return false;
  return true;
}

/** Цель привязана к фильтру в адресе: сам раздел без фильтра этому пункту не принадлежит. */
function isQueryBound(target: NavTarget): boolean {
  if (!target.to?.includes("?")) return false;
  return target.to.split("?")[0] === sectionOf(target.section)?.path.split("?")[0];
}

function byQuery(targets: readonly NavTarget[], pathname: string, search: string): boolean {
  return targets.some((t) => t.to !== undefined && hasQuery(t.to, pathname, search));
}

function bySection(targets: readonly NavTarget[], also: readonly string[], ref: string): boolean {
  return also.includes(ref) || targets.some((t) => t.section === ref && !isQueryBound(t));
}

/** Пункт меню для открытого адреса: сначала пункты с фильтром в адресе, затем по разделу. */
export function findNavItem(
  match: SectionMatch,
  pathname: string,
  search: string,
): NavHit | undefined {
  const ref = `${match.module.code}.${match.section.key}`;
  const entries = MODULES.flatMap((m) =>
    NAVIGATION[m.code].map((item) => ({ code: m.code, item })),
  );
  const ownsObject = (tab: NavTab) => match.objectId !== undefined && tab.objects?.includes(ref);
  const hit =
    entries.find(({ item }) =>
      [item, ...(item.tabs ?? [])].some((node) => byQuery(node.targets, pathname, search)),
    ) ??
    entries.find(({ item }) => item.tabs?.some(ownsObject)) ??
    entries.find(({ item }) => bySection(item.targets, item.also ?? [], ref));
  if (!hit) return undefined;
  const tabs = hit.item.tabs ?? [];
  const tab =
    tabs.find((t) => byQuery(t.targets, pathname, search)) ??
    tabs.find(ownsObject) ??
    tabs.find((t) => bySection(t.targets, t.also ?? [], ref));
  return { module: hit.code, item: hit.item, tab };
}
