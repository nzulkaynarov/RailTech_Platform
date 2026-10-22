import {
  SYSTEM_ROLES,
  TEMPLATES,
  mergeAccess,
  modulesOf,
  RESTRICTED_FIELDS,
  type AccessLevel,
  type CatalogRole,
  type RestrictedField,
} from "../../app/rbac.generated";
import type { ModuleCode, Role, RoleRef } from "../../shared/api/generated/model";

/**
 * Роли Платформы для MSW (ADR-0012): данные, как в CRM. При первом запуске — две системные роли и четыре роли из шаблонов
 * каталога `platform-rbac.yaml` (id 1–6, как в тестах BFF); дальше администратор создаёт, переименовывает и удаляет роли
 * в Admin · Ролевая матрица. Хранятся в `localStorage` страницы (как сессия мока), без хранилища — в памяти.
 * `demo` — какой набор демо-данных Dashboard показывать роли (только для моков: интерфейс на коды не опирается).
 */
export type PresetCode = "ADMIN" | "DIRECTOR" | "MANAGER" | "SUPPLY" | "ENGINEER" | "ACCOUNTANT";

export const ROLE_ID: Record<PresetCode, string> = {
  ADMIN: "1",
  DIRECTOR: "2",
  MANAGER: "3",
  SUPPLY: "4",
  ENGINEER: "5",
  ACCOUNTANT: "6",
};

export interface MockRole {
  id: string;
  name: string;
  description: string;
  system: boolean;
  code?: string;
  access: Partial<Record<string, AccessLevel>>;
  restricted_fields: RestrictedField[];
  updated_at: string;
  demo?: PresetCode;
}

const KEY = "rt-pf-mock-roles";
const SEEDED_AT = "2026-10-23T06:00:00.000Z";

const DESCRIPTIONS: Partial<Record<PresetCode, string>> = {
  ADMIN: "Сотрудники, роли, интеграции и тикеты; бизнес-данные по умолчанию не видит.",
  DIRECTOR: "Все бизнес-разделы и утверждения: резолюция, одобрение КП, служебные записки.",
  MANAGER: "Лиды, клиенты и заявки; переписка с клиентом.",
  SUPPLY: "Расчёт товаров, склад и поставщики.",
  ENGINEER: "Расчёт услуг, склад и документация.",
  ACCOUNTANT: "Счета, оплаты, акты и сканы договоров.",
};

function fromCatalog(code: PresetCode, role: CatalogRole, system: boolean): MockRole {
  return {
    id: ROLE_ID[code],
    name: role.name.ru,
    description: DESCRIPTIONS[code] ?? "",
    system,
    code: system ? code : `tpl:${code}`,
    access: { ...role.access },
    restricted_fields: [...role.restricted_fields],
    updated_at: SEEDED_AT,
    demo: code,
  };
}

export function seedRoles(): MockRole[] {
  return [
    fromCatalog("ADMIN", SYSTEM_ROLES.ADMIN, true),
    fromCatalog("DIRECTOR", SYSTEM_ROLES.DIRECTOR, true),
    fromCatalog("MANAGER", TEMPLATES.MANAGER, false),
    fromCatalog("SUPPLY", TEMPLATES.SUPPLY, false),
    fromCatalog("ENGINEER", TEMPLATES.ENGINEER, false),
    fromCatalog("ACCOUNTANT", TEMPLATES.ACCOUNTANT, false),
  ];
}

let memory: MockRole[] | null = null;

export function readRoles(): MockRole[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as MockRole[]) : seedRoles();
  } catch {
    memory ??= seedRoles();
    return memory;
  }
}

export function writeRoles(items: MockRole[]): void {
  memory = items;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetRoles(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего очищать.
  }
}

export function roleRefOf(role: MockRole): RoleRef {
  return {
    id: role.id,
    name: role.name,
    system: role.system,
    ...(role.code ? { code: role.code } : {}),
  };
}

/** Роли по id в порядке выдачи; удалённые пропускаются. */
export function rolesOf(
  ids: readonly string[],
  all: readonly MockRole[] = readRoles(),
): MockRole[] {
  return ids.flatMap((id) => all.filter((r) => r.id === id));
}

export function toRole(role: MockRole, employees: number): Role {
  return {
    id: role.id,
    name: role.name,
    description: role.description,
    system: role.system,
    ...(role.code ? { code: role.code } : {}),
    access: role.access as Role["access"],
    restricted_fields: role.restricted_fields,
    employees,
    updated_at: role.updated_at,
  };
}

export interface ComputedAccess {
  modules: ModuleCode[];
  resources: Partial<Record<string, AccessLevel>>;
  restricted_fields: RestrictedField[];
}

/** Объединение матриц ролей (как BFF): максимум по разделу, поля — объединение, модули — по видимым пунктам меню. */
export function computeAccess(roles: readonly MockRole[]): ComputedAccess {
  const resources = mergeAccess(roles.map((r) => r.access));
  const held = new Set(roles.flatMap((r) => r.restricted_fields));
  return {
    modules: modulesOf(resources),
    resources,
    restricted_fields: (Object.keys(RESTRICTED_FIELDS) as RestrictedField[]).filter((f) =>
      held.has(f),
    ),
  };
}
