import { RESOURCE_KEYS, type AccessLevel } from "../../app/rbac.generated";
import type { RoleSnapshot } from "../../shared/api/generated/model";

/** Что изменилось в роли между двумя снимками аудита CRM: название, описание, уровни разделов, поля. */
export interface RoleDiff {
  name?: { from: string; to: string };
  description: boolean;
  sections: { resource: string; from?: AccessLevel; to?: AccessLevel }[];
  fields: { field: string; visible: boolean }[];
}

const order = (key: string) => {
  const index = (RESOURCE_KEYS as readonly string[]).indexOf(key);
  return index < 0 ? RESOURCE_KEYS.length : index;
};

export function roleDiff(before?: RoleSnapshot, after?: RoleSnapshot): RoleDiff {
  const was = before?.access ?? {};
  const now = after?.access ?? {};
  const keys = [...new Set([...Object.keys(was), ...Object.keys(now)])].sort(
    (a, b) => order(a) - order(b) || a.localeCompare(b),
  );
  const wasFields = new Set(before?.restricted_fields ?? []);
  const nowFields = new Set(after?.restricted_fields ?? []);
  const fieldKeys = [...new Set([...wasFields, ...nowFields])].sort();
  return {
    ...(before && after && before.name !== after.name
      ? { name: { from: before.name, to: after.name } }
      : {}),
    description: Boolean(before && after && before.description !== after.description),
    sections: keys
      .filter((key) => was[key] !== now[key])
      .map((resource) => ({
        resource,
        ...(was[resource] ? { from: was[resource] } : {}),
        ...(now[resource] ? { to: now[resource] } : {}),
      })),
    fields: fieldKeys
      .filter((field) => wasFields.has(field) !== nowFields.has(field))
      .map((field) => ({ field, visible: nowFields.has(field) })),
  };
}

export const isEmptyDiff = (diff: RoleDiff) =>
  !diff.name && !diff.description && diff.sections.length === 0 && diff.fields.length === 0;
