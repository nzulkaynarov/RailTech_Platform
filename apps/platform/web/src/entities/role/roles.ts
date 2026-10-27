import {
  RESOURCES,
  RESTRICTED_FIELDS,
  mergeAccess,
  modulesOf,
  sectionsWithBackend,
  type Access,
  type AccessLevel,
  type ModuleCode,
  type ResourceKey,
  type RestrictedField,
} from "../../app/rbac.generated";
import type { Me, Role, RoleRef } from "../../shared/api/generated/model";

/**
 * Роли Платформы — данные (ADR-0012): названия и матрицы приходят из API. Интерфейс опирается только на два системных
 * кода (`ADMIN`, `DIRECTOR`) и на разделы каталога; коды ролей-шаблонов не используются.
 */
type WithCode = Pick<RoleRef, "system" | "code">;

export const isSystemAdmin = (role: WithCode) => role.system && role.code === "ADMIN";
export const isSystemDirector = (role: WithCode) => role.system && role.code === "DIRECTOR";

export type Language = "ru" | "uz" | "en";

export function lang(language: string): Language {
  return language === "uz" || language === "en" ? language : "ru";
}

/** Подпись раздела каталога в строке матрицы: без префикса модуля («Клиенты · …»), он — в заголовке группы. */
export function sectionLabel(key: ResourceKey, language: string): string {
  const label = RESOURCES[key].label[lang(language)];
  // Подпись каталога начинается с имени модуля («Клиенты · …»); в матрице строка стоит под заголовком модуля.
  return label.replace(/^[^·]+ · /, "");
}

/** Полная подпись раздела (с модулем) — для списков «получат / потеряют». */
export function sectionFullLabel(key: string, language: string): string {
  return key in RESOURCES ? RESOURCES[key as ResourceKey].label[lang(language)] : key;
}

export function fieldLabel(field: string, language: string): string {
  return field in RESTRICTED_FIELDS
    ? RESTRICTED_FIELDS[field as RestrictedField][lang(language)]
    : field;
}

/** Роли «вида» сотрудника словами: активная или все; несколько без выбора — «Все роли». */
export function viewRoleNames(me: Me, allRoles: string): string {
  const active = me.roles.find((role) => role.id === me.active_role);
  if (active) return active.name;
  if (me.roles.length > 1) return allRoles;
  return me.roles[0]?.name ?? "";
}

/** Матрица набора ролей (объединение, как у BFF) и что из неё следует. */
export interface RolesAccess {
  access: Partial<Record<ResourceKey, AccessLevel>>;
  modules: ModuleCode[];
  erp: boolean;
  /** Системная роль «Администратор» среди выбранных: полный администратор CRM и ERP */
  systemAdmin: boolean;
  /** Раздел Admin «полный» без системной роли «Администратор» (решение R-1: полного admin CRM не даёт) */
  adminWithoutSystem: boolean;
}

export function rolesAccess(
  roles: readonly Pick<Role, "access" | "system" | "code">[],
): RolesAccess {
  const access = mergeAccess(roles.map((role) => role.access as Access));
  const systemAdmin = roles.some(isSystemAdmin);
  return {
    access,
    modules: modulesOf(access),
    erp: sectionsWithBackend(access, "erp").length > 0,
    systemAdmin,
    adminWithoutSystem: !systemAdmin && access.admin === "full",
  };
}
