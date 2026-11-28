import { HttpResponse, http } from "msw";

import type { EmployeeInvite, EmployeeUpdate } from "../shared/api/generated/model";
import {
  type MockEmployee,
  accessFor,
  readEmployees,
  readPendingPasswordIds,
  toEmployee,
  writeEmployees,
  writePendingPasswordIds,
} from "./fixtures/employees";
import { recordAudit } from "./fixtures/audit";
import { ROLE_ID, readRoles } from "./fixtures/roles";
import { buildMe, currentActor, readSession } from "./mockSession";
import { rememberTemporaryPassword, registerUser, updateExtraUser } from "./fixtures/users";
import { stepUpRefusal } from "./secondFactor";
import { markStepDone } from "./setupState";
import { deputyRefusal } from "./profileHandlers";
import { patchProfile, readProfile } from "./profileStore";

export function failure(
  status: number,
  code: string,
  message: string,
  source: "bff" | "crm" | "erp" | "eds" = "bff",
  details?: Record<string, unknown>,
) {
  return HttpResponse.json({ code, message, source, ...(details ? { details } : {}) }, { status });
}

type Level = "full" | "read" | undefined;

function adminLevel(): Level | "no-session" {
  const session = readSession();
  if (!session) return "no-session";
  // Права операций — по объединению ролей.
  const all = buildMe(session);
  if (!all) return "no-session";
  return all.resources["admin"];
}

/** Проверка раздела `admin` как у BFF: нет сессии — 401, нет раздела — 403, запись — только full. */
export function guard(need: "read" | "full") {
  const level = adminLevel();
  if (level === "no-session") return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  if (!level || (need === "full" && level !== "full")) {
    return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
      resource: "admin",
      need,
    });
  }
  return null;
}

/** Активные сотрудники с системной ролью кроме этого (инварианты CRM «≥ 1 администратор и директор»). */
const activeHolders = (items: readonly MockEmployee[], roleId: string, excluding: string) =>
  items.filter((e) => e.id !== excluding && e.status !== "disabled" && e.role_ids.includes(roleId))
    .length;

const LAST = {
  [ROLE_ID.ADMIN]: {
    code: "LAST_ADMIN",
    text: "Нельзя снять роль администратора или отключить последнего администратора. Сначала назначьте администратором другого сотрудника.",
  },
  [ROLE_ID.DIRECTOR]: {
    code: "LAST_DIRECTOR",
    text: "Нельзя снять роль директора или отключить последнего директора. Сначала назначьте директором другого сотрудника.",
  },
} as const;

function sorted(items: readonly MockEmployee[]) {
  return [...items].sort((a, b) => a.name.localeCompare(b.name, "ru"));
}

/** Временный пароль мока — случайный на каждый вызов (ни одного литерала, похожего на настоящий пароль). */
export function randomTemporaryPassword(): string {
  const bytes = new Uint8Array(9);
  globalThis.crypto.getRandomValues(bytes);
  return `Tmp-${Array.from(bytes, (b) => b.toString(36).padStart(2, "0")).join("")}`;
}

/** Моки `/admin/users*` (PLT-15, R-2): состояние в `fixtures/employees`, инварианты — как у CRM. */
export const adminUsersHandlers = [
  http.get("*/admin/users", ({ request }) => {
    const denied = guard("read");
    if (denied) return denied;
    const url = new URL(request.url);
    const q = (url.searchParams.get("q") ?? "").trim().toLocaleLowerCase();
    const status = url.searchParams.get("status");
    const stored = readEmployees();
    const items = sorted(stored)
      .filter((e) => !status || e.status === status)
      .filter(
        (e) => !q || `${e.name} ${e.email} ${e.position ?? ""}`.toLocaleLowerCase().includes(q),
      )
      .map(toEmployee)
      .map((e) => (readProfile(e.id).showTest === true ? { ...e, show_test: true } : e));
    // ERP отвечает между чтениями: «выдаётся» в этом ответе — «ок» в следующем (как очередь CRM).
    if (stored.some((e) => e.erp_sync === "pending")) {
      writeEmployees(
        stored.map((e) => (e.erp_sync === "pending" ? { ...e, erp_sync: "ok" as const } : e)),
      );
    }
    return HttpResponse.json({ items });
  }),

  http.post("*/admin/users", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    // ДВ-4б: роль при создании — выдача роли, нужен свежий код второго фактора
    const refusal = stepUpRefusal(request);
    if (refusal) return refusal;
    const body = (await request.json()) as EmployeeInvite;
    const items = readEmployees();
    const email = body.email.trim().toLowerCase();
    if (items.some((e) => e.email.toLowerCase() === email)) {
      return failure(409, "EMAIL_EXISTS", "Сотрудник с такой почтой уже есть.", "crm");
    }
    const known = new Set(readRoles().map((r) => r.id));
    if (body.role_ids.some((id) => !known.has(id))) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "crm", {
        fields: ["role_ids"],
      });
    }
    const name = body.name.trim();
    const employee: MockEmployee = {
      id: `u-demo-new-${String(items.length + 1)}`,
      name,
      initials: name
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part.charAt(0).toLocaleUpperCase())
        .join(""),
      email,
      ...(body.position?.trim() ? { position: body.position.trim() } : {}),
      role_ids: body.role_ids,
      access: accessFor(body.role_ids),
      status: "invited",
      telegram_linked: false,
      telegram: "not_linked",
      erp_sync: "pending",
    };
    writeEmployees([...items, employee]);
    markStepDone("first_employee");
    // Сотрудник может войти только с этим паролем и обязан сменить его (`must_change_password`).
    const password = randomTemporaryPassword();
    registerUser({
      id: employee.id,
      email,
      name,
      initials: employee.initials,
      position: employee.position ?? "—",
      roles: [],
      language: "ru",
      mustChangePassword: true,
    });
    rememberTemporaryPassword(email, password);
    return HttpResponse.json(
      { employee: toEmployee(employee), temporary_password: password },
      { status: 201, headers: { "Cache-Control": "no-store" } },
    );
  }),

  http.post("*/admin/users/:id/temporary-password", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const session = readSession();
    if (session && session.userId === params["id"]) {
      return failure(409, "CONFLICT", "Свой пароль меняется в профиле.", "bff", {
        reason: "own_account",
      });
    }
    const items = readEmployees();
    const current = items.find((e) => e.id === params["id"]);
    if (!current) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    const pending = new Set(readPendingPasswordIds());
    pending.add(current.id);
    writePendingPasswordIds([...pending]);
    const next: MockEmployee =
      current.status === "disabled" ? current : { ...current, status: "invited" };
    writeEmployees(items.map((e) => (e.id === next.id ? next : e)));
    const password = randomTemporaryPassword();
    rememberTemporaryPassword(next.email, password);
    updateExtraUser(next.id, { mustChangePassword: true });
    recordAudit(currentActor(), {
      action: "user.reset_password",
      entityType: "user",
      entityId: next.id,
    });
    return HttpResponse.json(
      { employee: toEmployee(next), temporary_password: password },
      { headers: { "Cache-Control": "no-store" } },
    );
  }),

  http.post("*/admin/users/invite", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    // ДВ-4б: роль при создании — выдача роли, нужен свежий код второго фактора
    const refusal = stepUpRefusal(request);
    if (refusal) return refusal;
    const body = (await request.json()) as EmployeeInvite;
    const items = readEmployees();
    const email = body.email.trim().toLowerCase();
    if (items.some((e) => e.email.toLowerCase() === email)) {
      return failure(409, "EMAIL_EXISTS", "Сотрудник с такой почтой уже есть.", "crm");
    }
    const known = new Set(readRoles().map((r) => r.id));
    if (body.role_ids.some((id) => !known.has(id))) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "crm", {
        fields: ["role_ids"],
      });
    }
    const name = body.name.trim();
    const employee: MockEmployee = {
      id: `u-demo-new-${String(items.length + 1)}`,
      name,
      initials: name
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part.charAt(0).toLocaleUpperCase())
        .join(""),
      email,
      ...(body.position?.trim() ? { position: body.position.trim() } : {}),
      role_ids: body.role_ids,
      access: accessFor(body.role_ids),
      status: "invited",
      telegram_linked: false,
      telegram: "not_linked",
      erp_sync: "pending",
    };
    writeEmployees([...items, employee]);
    // Адрес nomail@ показывает путь «почта не подключена»: сотрудник создан, письмо не ушло.
    if (email.startsWith("nomail@")) {
      return failure(409, "CONFLICT", "Сотрудник добавлен, но письмо не отправлено.", "crm", {
        employee_id: employee.id,
        invite: "not_sent",
        reason: "smtp_not_configured",
      });
    }
    markStepDone("first_employee");
    return HttpResponse.json(toEmployee(employee), { status: 201 });
  }),

  http.post("*/admin/users/:id/invite", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const employee = readEmployees().find((e) => e.id === params["id"]);
    if (!employee) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    if (employee.email.startsWith("nomail@")) {
      return failure(409, "CONFLICT", "Письмо не отправлено.", "crm", {
        employee_id: employee.id,
        invite: "not_sent",
        reason: "smtp_not_configured",
      });
    }
    return HttpResponse.json(toEmployee(employee));
  }),

  http.post("*/admin/users/:id/erp-sync", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const items = readEmployees();
    const current = items.find((e) => e.id === params["id"]);
    if (!current) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    // Ошибка снята, задача в очереди: «выдаётся», следующее чтение списка — «ок».
    const next: MockEmployee = { ...current, erp_sync: "pending" };
    delete next.erp_sync_error;
    writeEmployees(items.map((e) => (e.id === next.id ? next : e)));
    return HttpResponse.json(toEmployee(next));
  }),

  http.patch("*/admin/users/:id", async ({ request, params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as EmployeeUpdate;
    const items = readEmployees();
    const current = items.find((e) => e.id === params["id"]);
    if (!current) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    // ДВ-4б: выдача роли (появилась роль, которой не было) — со свежим кодом второго фактора
    if (body.role_ids?.some((id) => !current.role_ids.includes(id))) {
      const refusal = stepUpRefusal(request);
      if (refusal) return refusal;
    }
    // СОТР-1: замещение за сотрудника — те же правила и журнал, что у «Профиля»; `null` снимает
    if (body.deputy !== undefined) {
      if (body.deputy !== null) {
        const refusal = deputyRefusal(current.id, body.deputy);
        if (refusal) return refusal;
        patchProfile(current.id, {
          deputy: {
            id: body.deputy.deputy_id,
            date_from: body.deputy.date_from,
            date_to: body.deputy.date_to,
          },
        });
        recordAudit(currentActor(), {
          action: "user.deputy_set",
          entityType: "user",
          entityId: current.id,
        });
      } else {
        patchProfile(current.id, { deputy: undefined });
        recordAudit(currentActor(), {
          action: "user.deputy_cleared",
          entityType: "user",
          entityId: current.id,
        });
      }
      if (Object.keys(body).length === 1) return HttpResponse.json(toEmployee(current));
    }
    // Как BFF 0.6.0: пустой набор ролей в CRM не уходит (закрыть доступ — «Отключить сотрудника»).
    if (body.role_ids !== undefined && body.role_ids.length === 0) {
      return failure(
        422,
        "ROLES_REQUIRED",
        "Нужна хотя бы одна роль. Чтобы закрыть сотруднику доступ, отключите его.",
        "bff",
        { fields: ["role_ids"] },
      );
    }

    for (const roleId of [ROLE_ID.ADMIN, ROLE_ID.DIRECTOR]) {
      const drops =
        current.role_ids.includes(roleId) &&
        ((body.role_ids !== undefined && !body.role_ids.includes(roleId)) ||
          body.is_active === false);
      if (drops && activeHolders(items, roleId, current.id) === 0) {
        const rule = LAST[roleId];
        if (!rule) continue;
        return failure(409, rule.code, rule.text, "crm", {
          backend_status: 409,
          backend_code: rule.code.toLowerCase(),
          reason: rule.code.toLowerCase(),
        });
      }
    }

    // Как CRM: у кого пароль ещё временный, после включения снова «Приглашён».
    const pending = new Set(readPendingPasswordIds());
    if (current.status === "invited") pending.add(current.id);
    writePendingPasswordIds([...pending]);

    const roleIds = body.role_ids ?? current.role_ids;
    const next: MockEmployee = {
      ...current,
      role_ids: roleIds,
      access: accessFor(roleIds),
      ...(body.is_active === undefined
        ? {}
        : {
            status: body.is_active ? (pending.has(current.id) ? "invited" : "active") : "disabled",
          }),
    };
    if (body.is_service !== undefined) next.is_service = body.is_service;
    if (body.position !== undefined) {
      if (body.position.trim()) next.position = body.position.trim();
      else delete next.position;
    }
    writeEmployees(items.map((e) => (e.id === next.id ? next : e)));
    const roleNames = (ids: string[]) =>
      toEmployee({ ...current, role_ids: ids }).roles.map((r) => r.name);
    recordAudit(currentActor(), {
      action: "user.update",
      entityType: "user",
      entityId: next.id,
      before: {
        platform_role_names: roleNames(current.role_ids),
        is_active: current.status !== "disabled",
      },
      after: {
        platform_role_names: roleNames(next.role_ids),
        is_active: next.status !== "disabled",
      },
    });
    return HttpResponse.json(toEmployee(next));
  }),
];
