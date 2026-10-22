// ГЕНЕРИРУЕТСЯ — не править руками (PLT-11).
// Источник: packages/contracts/platform-rbac.yaml (version 1).
// Пересоздание: make -C apps/platform rbac; make check-platform сверяет файл с контрактом
// Матрица, меню и поля с ограничением — один источник с BFF (bff/app/rbac_generated.py).

export const ROLES = ["MANAGER", "DIRECTOR", "SUPPLY", "ENGINEER", "ACCOUNTANT", "ADMIN"] as const;
export type RoleCode = (typeof ROLES)[number];

export const MODULES = ["dashboard", "crm", "eds", "erp", "chats", "admin"] as const;
export type ModuleCode = (typeof MODULES)[number];

export type AccessLevel = "full" | "read" | "hidden";

export const ROLE_NAMES: Record<RoleCode, { ru: string; uz: string; en: string }> = {
  MANAGER: {
    ru: "Менеджер",
    uz: "Menejer",
    en: "Manager",
  },
  DIRECTOR: {
    ru: "Директор",
    uz: "Direktor",
    en: "Director",
  },
  SUPPLY: {
    ru: "Снабженец",
    uz: "Ta'minotchi",
    en: "Supply specialist",
  },
  ENGINEER: {
    ru: "Гл. инженер",
    uz: "Bosh muhandis",
    en: "Chief engineer",
  },
  ACCOUNTANT: {
    ru: "Бухгалтер",
    uz: "Buxgalter",
    en: "Accountant",
  },
  ADMIN: {
    ru: "Администратор",
    uz: "Administrator",
    en: "Administrator",
  },
};

/** Роли ERP, которые CRM выдаёт роли Платформы (docs/architecture/integration-map.md §4); у ADMIN пусто: суперпользователь ERP. */
export const ERP_ROLE_CODES = {
  MANAGER: ["VIEWER"],
  DIRECTOR: ["HEAD"],
  SUPPLY: ["CATALOG_SUPPLY", "FULFILLMENT"],
  ENGINEER: ["FULFILLMENT"],
  ACCOUNTANT: ["FINANCE"],
  ADMIN: [],
} as const satisfies Record<RoleCode, readonly string[]>;

/** Права ERP поверх шаблонов ролей ERP. */
export const ERP_EXTRA_PERMISSIONS = {
  MANAGER: ["deal.manage"],
  DIRECTOR: [],
  SUPPLY: ["quote.build", "quote.edit_pricing"],
  ENGINEER: ["quote.build"],
  ACCOUNTANT: ["contract.manage", "fulfillment.act"],
  ADMIN: [],
} as const satisfies Record<RoleCode, readonly string[]>;

/** Матрица SPEC-v3 §4.2: раздел -> модуль и уровень по каждой роли. */
export const RESOURCES = {
  "dashboard.queue": {
    module: "dashboard",
    access: {
      MANAGER: "full",
      DIRECTOR: "full",
      SUPPLY: "full",
      ENGINEER: "full",
      ACCOUNTANT: "full",
      ADMIN: "full",
    },
  },
  "dashboard.summary": {
    module: "dashboard",
    access: {
      MANAGER: "hidden",
      DIRECTOR: "full",
      SUPPLY: "hidden",
      ENGINEER: "hidden",
      ACCOUNTANT: "read",
      ADMIN: "hidden",
    },
  },
  "crm.leads": {
    module: "crm",
    access: {
      MANAGER: "full",
      DIRECTOR: "read",
      SUPPLY: "hidden",
      ENGINEER: "hidden",
      ACCOUNTANT: "hidden",
      ADMIN: "hidden",
    },
  },
  "crm.clients": {
    module: "crm",
    access: {
      MANAGER: "full",
      DIRECTOR: "read",
      SUPPLY: "read",
      ENGINEER: "read",
      ACCOUNTANT: "read",
      ADMIN: "hidden",
    },
  },
  "eds.inbox": {
    module: "eds",
    access: {
      MANAGER: "read",
      DIRECTOR: "full",
      SUPPLY: "hidden",
      ENGINEER: "hidden",
      ACCOUNTANT: "read",
      ADMIN: "hidden",
    },
  },
  "eds.drafts": {
    module: "eds",
    access: {
      MANAGER: "read",
      DIRECTOR: "full",
      SUPPLY: "hidden",
      ENGINEER: "hidden",
      ACCOUNTANT: "hidden",
      ADMIN: "hidden",
    },
  },
  "eds.projects": {
    module: "eds",
    access: {
      MANAGER: "read",
      DIRECTOR: "full",
      SUPPLY: "read",
      ENGINEER: "read",
      ACCOUNTANT: "full",
      ADMIN: "hidden",
    },
  },
  "eds.payments": {
    module: "eds",
    access: {
      MANAGER: "read",
      DIRECTOR: "read",
      SUPPLY: "hidden",
      ENGINEER: "hidden",
      ACCOUNTANT: "full",
      ADMIN: "hidden",
    },
  },
  "eds.memo.create": {
    module: "eds",
    access: {
      MANAGER: "full",
      DIRECTOR: "full",
      SUPPLY: "full",
      ENGINEER: "full",
      ACCOUNTANT: "full",
      ADMIN: "full",
    },
  },
  "eds.memo.approve": {
    module: "eds",
    access: {
      MANAGER: "hidden",
      DIRECTOR: "full",
      SUPPLY: "hidden",
      ENGINEER: "hidden",
      ACCOUNTANT: "hidden",
      ADMIN: "hidden",
    },
  },
  "erp.calc": {
    module: "erp",
    access: {
      MANAGER: "hidden",
      DIRECTOR: "full",
      SUPPLY: "full",
      ENGINEER: "full",
      ACCOUNTANT: "read",
      ADMIN: "hidden",
    },
  },
  "erp.stock": {
    module: "erp",
    access: {
      MANAGER: "read",
      DIRECTOR: "full",
      SUPPLY: "full",
      ENGINEER: "full",
      ACCOUNTANT: "read",
      ADMIN: "hidden",
    },
  },
  "chats.internal": {
    module: "chats",
    access: {
      MANAGER: "full",
      DIRECTOR: "full",
      SUPPLY: "full",
      ENGINEER: "full",
      ACCOUNTANT: "full",
      ADMIN: "full",
    },
  },
  "chats.external": {
    module: "chats",
    access: {
      MANAGER: "full",
      DIRECTOR: "read",
      SUPPLY: "hidden",
      ENGINEER: "hidden",
      ACCOUNTANT: "full",
      ADMIN: "hidden",
    },
  },
  admin: {
    module: "admin",
    access: {
      MANAGER: "hidden",
      DIRECTOR: "read",
      SUPPLY: "hidden",
      ENGINEER: "hidden",
      ACCOUNTANT: "hidden",
      ADMIN: "full",
    },
  },
} as const satisfies Record<string, { module: ModuleCode; access: Record<RoleCode, AccessLevel> }>;
export type ResourceKey = keyof typeof RESOURCES;

/** Меню (Q-PLT-12-2): модуль -> пункт -> разделы матрицы (виден любой из них). */
export const MENU = {
  dashboard: {
    queue: ["dashboard.queue"],
    projects: ["eds.projects"],
    summary: ["dashboard.summary"],
  },
  crm: {
    messages: ["crm.leads"],
    leads: ["crm.leads"],
    clients: ["crm.clients"],
    requests: ["crm.clients"],
    channels: ["crm.leads"],
    kb: ["crm.leads"],
  },
  eds: {
    documents: [
      "eds.inbox",
      "eds.drafts",
      "eds.projects",
      "eds.payments",
      "eds.memo.create",
      "eds.memo.approve",
    ],
    inbox: ["eds.inbox"],
    outbox: ["eds.drafts"],
    projects: ["eds.projects"],
    drafts: ["eds.drafts"],
    approvals: ["eds.memo.approve", "eds.memo.create"],
    payments: ["eds.payments"],
  },
  erp: {
    requests: ["erp.calc"],
    calc: ["erp.calc"],
    stock: ["erp.stock"],
    catalog: ["erp.stock"],
    docs: ["erp.stock"],
  },
  chats: {
    all: ["chats.internal", "chats.external"],
    internal: ["chats.internal"],
    external: ["chats.external"],
    contacts: ["chats.internal"],
  },
  admin: {
    roles: ["admin"],
    org: ["admin"],
    integrations: ["admin"],
    tickets: ["admin"],
  },
} as const satisfies Record<ModuleCode, Record<string, readonly ResourceKey[]>>;

/** Поля с ограничением (SPEC-v3 §4.2): группа -> роли, которым она видна. */
export const RESTRICTED_FIELDS = {
  cost_margin: ["DIRECTOR", "SUPPLY"],
  totals_only: ["ACCOUNTANT"],
  supplier_prices: ["DIRECTOR", "SUPPLY", "ACCOUNTANT"],
} as const satisfies Record<string, readonly RoleCode[]>;
export type RestrictedField = keyof typeof RESTRICTED_FIELDS;

const RANK: Record<AccessLevel, number> = { hidden: 0, read: 1, full: 2 };

/** Уровень раздела у набора ролей: максимум по ролям (full > read > hidden). */
export function levelFor(roles: readonly RoleCode[], resource: ResourceKey): AccessLevel {
  let best: AccessLevel = "hidden";
  for (const role of roles) {
    const level: AccessLevel = RESOURCES[resource].access[role];
    if (RANK[level] > RANK[best]) best = level;
  }
  return best;
}

/** Раздел виден (read или full). */
export function canSee(roles: readonly RoleCode[], resource: ResourceKey): boolean {
  return levelFor(roles, resource) !== "hidden";
}

/** Действие в разделе разрешено: `need` = "read" — чтение, "full" — изменение. */
export function allows(
  roles: readonly RoleCode[],
  resource: ResourceKey,
  need: Exclude<AccessLevel, "hidden"> = "read",
): boolean {
  return RANK[levelFor(roles, resource)] >= RANK[need];
}

/** Модули рейла в порядке показа: виден хотя бы один раздел модуля. */
export function visibleModules(roles: readonly RoleCode[]): ModuleCode[] {
  return MODULES.filter((module) =>
    (Object.keys(RESOURCES) as ResourceKey[]).some(
      (key) => RESOURCES[key].module === module && canSee(roles, key),
    ),
  );
}

/** Пункт меню виден, если виден хотя бы один из его разделов (`any_of`). */
export function menuItemVisible(
  roles: readonly RoleCode[],
  module: ModuleCode,
  item: string,
): boolean {
  const sections = (MENU[module] as Record<string, readonly ResourceKey[]>)[item];
  return sections?.some((key) => canSee(roles, key)) ?? false;
}

/** Видимые пункты меню модуля в порядке контракта. */
export function visibleMenuItems(roles: readonly RoleCode[], module: ModuleCode): string[] {
  return Object.keys(MENU[module]).filter((item) => menuItemVisible(roles, module, item));
}

/** Группы полей с ограничением, видимые хотя бы одной из ролей. */
export function visibleRestrictedFields(roles: readonly RoleCode[]): RestrictedField[] {
  return (Object.keys(RESTRICTED_FIELDS) as RestrictedField[]).filter((field) =>
    roles.some((role) => (RESTRICTED_FIELDS[field] as readonly RoleCode[]).includes(role)),
  );
}
