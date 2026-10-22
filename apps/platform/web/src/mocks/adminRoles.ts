import { HttpResponse, http } from "msw";

import {
  RESOURCES,
  RESTRICTED_FIELDS,
  mergeAccess,
  type AccessLevel,
  type ResourceKey,
} from "../app/rbac.generated";
import type {
  RoleCreate,
  RoleImpact,
  RolePreviewIn,
  RoleUpdate,
  SectionLevel,
} from "../shared/api/generated/model";
import { failure, guard } from "./adminUsers";
import { readEmployees } from "./fixtures/employees";
import { type MockRole, readRoles, rolesOf, toRole, writeRoles } from "./fixtures/roles";

/**
 * Моки `/admin/roles*` (R-2, ADR-0012) с правилами CRM (R-1): системные роли неизменны (409 `ROLE_SYSTEM`), роль с
 * сотрудниками не удаляется (409 `ROLE_IN_USE`), название уникально без учёта регистра (409 `CONFLICT`,
 * `name_taken`), чужая правка роли — 409 `CONFLICT` (`role_version_conflict`, BFF 0.3.1), раздел и уровень — только из каталога (422). Предпросмотр считает, кто что получит и потеряет.
 */
const RANK: Record<AccessLevel, number> = { read: 1, full: 2 };

function holders(roleId: string): number {
  return readEmployees().filter((e) => e.role_ids.includes(roleId)).length;
}

function invalidAccess(access: Record<string, string> | undefined): boolean {
  return Object.entries(access ?? {}).some(([key, level]) => {
    const def = (RESOURCES as Record<string, { levels: readonly string[] }>)[key];
    return !def || !def.levels.includes(level);
  });
}

function invalidFields(fields: readonly string[] | undefined): boolean {
  return (fields ?? []).some((f) => !(f in RESTRICTED_FIELDS));
}

function validation(field: string) {
  return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "crm", {
    fields: [field],
  });
}

function nameTaken(name: string, except?: string) {
  const lower = name.trim().toLocaleLowerCase();
  return readRoles().some((r) => r.id !== except && r.name.toLocaleLowerCase() === lower);
}

const systemRefusal = () =>
  failure(409, "ROLE_SYSTEM", "Системную роль нельзя изменить или удалить.", "crm", {
    reason: "role_system",
  });

function diff(
  before: Partial<Record<string, AccessLevel>>,
  after: Partial<Record<string, AccessLevel>>,
): { gained: SectionLevel[]; lost: SectionLevel[] } {
  const gained: SectionLevel[] = [];
  const lost: SectionLevel[] = [];
  for (const key of Object.keys(RESOURCES) as ResourceKey[]) {
    const was = before[key];
    const now = after[key];
    const a = was ? RANK[was] : 0;
    const b = now ? RANK[now] : 0;
    if (b > a && now) gained.push({ resource: key, level: now });
    else if (b < a && was) lost.push({ resource: key, level: was });
  }
  return { gained, lost };
}

const unique = <T>(items: T[], key: (item: T) => string) => {
  const seen = new Set<string>();
  return items.filter((item) => (seen.has(key(item)) ? false : (seen.add(key(item)), true)));
};

export const adminRolesHandlers = [
  http.get("*/admin/roles", () => {
    const denied = guard("read");
    if (denied) return denied;
    return HttpResponse.json({ items: readRoles().map((r) => toRole(r, holders(r.id))) });
  }),

  http.post("*/admin/roles/preview", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as RolePreviewIn;
    const roles = readRoles();
    const target = body.role_id ? roles.find((r) => r.id === body.role_id) : undefined;
    if (body.role_id && !target) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    if (target?.system) return systemRefusal();
    if (invalidAccess(body.access)) return validation("access");
    if (!target) {
      return HttpResponse.json({
        role_id: null,
        employees_total: 0,
        employees: [],
        gained: [],
        lost: [],
        fields_gained: [],
        fields_lost: [],
      });
    }
    const draft: MockRole = {
      ...target,
      ...(body.access ? { access: body.access } : {}),
      ...(body.restricted_fields ? { restricted_fields: body.restricted_fields } : {}),
    };
    const employees: RoleImpact[] = [];
    const holdersList = readEmployees().filter((e) => e.role_ids.includes(target.id));
    for (const employee of holdersList) {
      const held = rolesOf(employee.role_ids, roles);
      const before = mergeAccess(held.map((r) => r.access));
      const after = mergeAccess(held.map((r) => (r.id === target.id ? draft : r).access));
      const fieldsBefore = new Set(held.flatMap((r) => r.restricted_fields));
      const fieldsAfter = new Set(
        held.flatMap((r) => (r.id === target.id ? draft : r).restricted_fields),
      );
      const { gained, lost } = diff(before, after);
      const fields_gained = [...fieldsAfter].filter((f) => !fieldsBefore.has(f));
      const fields_lost = [...fieldsBefore].filter((f) => !fieldsAfter.has(f));
      if (gained.length + lost.length + fields_gained.length + fields_lost.length === 0) continue;
      employees.push({
        employee: { id: employee.id, name: employee.name, initials: employee.initials },
        gained,
        lost,
        fields_gained,
        fields_lost,
      });
    }
    return HttpResponse.json({
      role_id: target.id,
      employees_total: holdersList.length,
      employees,
      gained: unique(
        employees.flatMap((e) => e.gained),
        (s) => s.resource,
      ),
      lost: unique(
        employees.flatMap((e) => e.lost),
        (s) => s.resource,
      ),
      fields_gained: [...new Set(employees.flatMap((e) => e.fields_gained))],
      fields_lost: [...new Set(employees.flatMap((e) => e.fields_lost))],
    });
  }),

  http.post("*/admin/roles", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as RoleCreate;
    if (nameTaken(body.name)) {
      return failure(409, "CONFLICT", "Роль с таким названием уже есть.", "crm", {
        reason: "name_taken",
      });
    }
    if (invalidAccess(body.access)) return validation("access");
    if (invalidFields(body.restricted_fields)) return validation("restricted_fields");
    const roles = readRoles();
    const id = String(Math.max(40, ...roles.map((r) => Number(r.id))) + 1);
    const role: MockRole = {
      id,
      name: body.name.trim(),
      description: body.description?.trim() ?? "",
      system: false,
      version: 1,
      access: body.access,
      restricted_fields: body.restricted_fields,
      updated_at: new Date().toISOString(),
    };
    writeRoles([...roles, role]);
    return HttpResponse.json(toRole(role, 0), { status: 201 });
  }),

  http.get("*/admin/roles/:id", ({ params }) => {
    const denied = guard("read");
    if (denied) return denied;
    const role = readRoles().find((r) => r.id === params["id"]);
    return role
      ? HttpResponse.json(toRole(role, holders(role.id)))
      : failure(404, "NOT_FOUND", "Не найдено.", "crm");
  }),

  http.patch("*/admin/roles/:id", async ({ request, params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as RoleUpdate;
    const roles = readRoles();
    const role = roles.find((r) => r.id === params["id"]);
    if (!role) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    if (role.system) return systemRefusal();
    if (body.version !== role.version) {
      return failure(
        409,
        "CONFLICT",
        "Роль изменена другим пользователем — обновите страницу.",
        "crm",
        { reason: "role_version_conflict", current_version: role.version },
      );
    }
    if (body.name !== undefined && nameTaken(body.name, role.id)) {
      return failure(409, "CONFLICT", "Роль с таким названием уже есть.", "crm", {
        reason: "name_taken",
      });
    }
    if (invalidAccess(body.access)) return validation("access");
    if (invalidFields(body.restricted_fields)) return validation("restricted_fields");
    const next: MockRole = {
      ...role,
      ...(body.name !== undefined ? { name: body.name.trim() } : {}),
      ...(body.description !== undefined ? { description: body.description.trim() } : {}),
      ...(body.access ? { access: body.access } : {}),
      ...(body.restricted_fields ? { restricted_fields: body.restricted_fields } : {}),
      version: role.version + 1,
      updated_at: new Date().toISOString(),
    };
    writeRoles(roles.map((r) => (r.id === next.id ? next : r)));
    return HttpResponse.json(toRole(next, holders(next.id)));
  }),

  http.delete("*/admin/roles/:id", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const roles = readRoles();
    const role = roles.find((r) => r.id === params["id"]);
    if (!role) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    if (role.system) return systemRefusal();
    const count = holders(role.id);
    if (count > 0) {
      return failure(
        409,
        "ROLE_IN_USE",
        `Роль выдана сотрудникам (${String(count)}). Сначала назначьте им другие роли в Оргструктуре, затем удалите роль.`,
        "crm",
        { employees: count, reason: "role_in_use" },
      );
    }
    writeRoles(roles.filter((r) => r.id !== role.id));
    return new HttpResponse(null, { status: 204 });
  }),
];
