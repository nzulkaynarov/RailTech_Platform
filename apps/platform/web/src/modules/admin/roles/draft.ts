import {
  RESOURCE_KEYS,
  RESTRICTED_FIELDS,
  TEMPLATES,
  type AccessLevel,
  type ResourceKey,
  type RestrictedField,
} from "../../../app/rbac.generated";
import type { Role } from "../../../shared/api/generated/model";

/** Черновик роли в редакторе матрицы: название, описание, уровни по разделам, поля с ограничением. */
export interface RoleDraft {
  name: string;
  description: string;
  access: Partial<Record<ResourceKey, AccessLevel>>;
  restricted_fields: RestrictedField[];
}

export const NEW_ROLE = "new";
export type TemplateKey = keyof typeof TEMPLATES;
export const TEMPLATE_KEYS = Object.keys(TEMPLATES) as TemplateKey[];

const FIELD_ORDER = Object.keys(RESTRICTED_FIELDS) as RestrictedField[];

export function draftOf(role: Role): RoleDraft {
  const access: RoleDraft["access"] = {};
  for (const key of RESOURCE_KEYS) {
    const level = (role.access as Partial<Record<string, AccessLevel>>)[key];
    if (level) access[key] = level;
  }
  return {
    name: role.name,
    description: role.description,
    access,
    restricted_fields: FIELD_ORDER.filter((f) => role.restricted_fields.includes(f)),
  };
}

/** Черновик новой роли: с нуля (все разделы скрыты) или копия шаблона каталога. */
export function newDraft(template: TemplateKey | null, name = ""): RoleDraft {
  if (!template) return { name, description: "", access: {}, restricted_fields: [] };
  const source = TEMPLATES[template];
  return {
    name,
    description: "",
    access: { ...source.access },
    restricted_fields: FIELD_ORDER.filter((f) =>
      (source.restricted_fields as readonly string[]).includes(f),
    ),
  };
}

export function setLevel(
  draft: RoleDraft,
  key: ResourceKey,
  level: AccessLevel | "hidden",
): RoleDraft {
  const access: RoleDraft["access"] = {};
  for (const k of RESOURCE_KEYS) {
    const value = k === key ? (level === "hidden" ? undefined : level) : draft.access[k];
    if (value) access[k] = value;
  }
  return { ...draft, access };
}

export function toggleField(draft: RoleDraft, field: RestrictedField, on: boolean): RoleDraft {
  const held = new Set(draft.restricted_fields);
  if (on) held.add(field);
  else held.delete(field);
  return { ...draft, restricted_fields: FIELD_ORDER.filter((f) => held.has(f)) };
}

const sameAccess = (a: RoleDraft["access"], b: RoleDraft["access"]) =>
  RESOURCE_KEYS.every((key) => a[key] === b[key]);

export interface DraftChanges {
  name: boolean;
  description: boolean;
  access: boolean;
  fields: boolean;
  any: boolean;
}

export function changesOf(base: RoleDraft, draft: RoleDraft): DraftChanges {
  const name = draft.name.trim() !== base.name;
  const description = draft.description.trim() !== base.description;
  const access = !sameAccess(base.access, draft.access);
  const fields = draft.restricted_fields.join() !== base.restricted_fields.join();
  return { name, description, access, fields, any: name || description || access || fields };
}
