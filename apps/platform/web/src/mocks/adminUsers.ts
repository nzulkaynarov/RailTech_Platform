import { HttpResponse, http } from "msw";

import type { Employee, EmployeeInvite, EmployeeUpdate } from "../shared/api/generated/model";
import { accessFor, readEmployees, writeEmployees } from "./fixtures/employees";
import { buildMe, readSession } from "./mockSession";

function failure(
  status: number,
  code: string,
  message: string,
  source: "bff" | "crm" = "bff",
  details?: Record<string, unknown>,
) {
  return HttpResponse.json({ code, message, source, ...(details ? { details } : {}) }, { status });
}

type Level = "full" | "read" | undefined;

function adminLevel(): Level | "no-session" {
  const session = readSession();
  const me = session ? buildMe(session) : undefined;
  return me ? me.resources["admin"] : "no-session";
}

/** Проверка раздела `admin` как у BFF: нет сессии — 401, нет раздела — 403, запись — только full. */
function guard(need: "read" | "full") {
  const level = adminLevel();
  if (level === "no-session") return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  if (!level || (need === "full" && level !== "full")) {
    return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
  }
  return null;
}

const activeAdmins = (items: readonly Employee[], excluding: string) =>
  items.filter((e) => e.id !== excluding && e.status !== "disabled" && e.roles.includes("ADMIN"))
    .length;

/** Моки `/admin/users*` (PLT-15): состояние в `fixtures/employees`, правило «последнего админа» — как у CRM. */
export const adminUsersHandlers = [
  http.get("*/admin/users", ({ request }) => {
    const denied = guard("read");
    if (denied) return denied;
    const url = new URL(request.url);
    const q = (url.searchParams.get("q") ?? "").trim().toLocaleLowerCase();
    const status = url.searchParams.get("status");
    const items = readEmployees()
      .filter((e) => !status || e.status === status)
      .filter(
        (e) => !q || `${e.name} ${e.email} ${e.position ?? ""}`.toLocaleLowerCase().includes(q),
      )
      .sort((a, b) => a.name.localeCompare(b.name, "ru"));
    return HttpResponse.json({ items });
  }),

  http.post("*/admin/users/invite", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as EmployeeInvite;
    const items = readEmployees();
    const email = body.email.trim().toLowerCase();
    if (items.some((e) => e.email.toLowerCase() === email)) {
      return failure(409, "EMAIL_EXISTS", "Сотрудник с такой почтой уже есть.", "crm");
    }
    const name = body.name.trim();
    const employee: Employee = {
      id: `u-demo-new-${String(items.length + 1)}`,
      name,
      initials: name
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part.charAt(0).toLocaleUpperCase())
        .join(""),
      email,
      ...(body.position?.trim() ? { position: body.position.trim() } : {}),
      roles: body.roles,
      access: accessFor(body.roles),
      status: "invited",
      telegram_linked: false,
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
    return HttpResponse.json(employee, { status: 201 });
  }),

  http.get("*/admin/users/:id", ({ params }) => {
    const denied = guard("read");
    if (denied) return denied;
    const employee = readEmployees().find((e) => e.id === params["id"]);
    return employee ? HttpResponse.json(employee) : failure(404, "NOT_FOUND", "Не найдено.", "crm");
  }),

  http.patch("*/admin/users/:id", async ({ request, params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as EmployeeUpdate;
    const items = readEmployees();
    const current = items.find((e) => e.id === params["id"]);
    if (!current) return failure(404, "NOT_FOUND", "Не найдено.", "crm");

    const dropsAdmin =
      current.roles.includes("ADMIN") &&
      ((body.roles !== undefined && !body.roles.includes("ADMIN")) || body.is_active === false);
    if (dropsAdmin && activeAdmins(items, current.id) === 0) {
      return failure(
        409,
        "LAST_ADMIN",
        "Нельзя снять роль администратора или отключить последнего администратора. Сначала назначьте администратором другого сотрудника.",
        "crm",
        { backend_status: 409, backend_code: "last_admin" },
      );
    }

    const roles = body.roles ?? current.roles;
    const next: Employee = {
      ...current,
      roles,
      access: accessFor(roles),
      ...(body.is_active === undefined
        ? {}
        : {
            status: body.is_active
              ? current.status === "invited"
                ? "invited"
                : "active"
              : "disabled",
          }),
    };
    if (body.position !== undefined) {
      if (body.position.trim()) next.position = body.position.trim();
      else delete next.position;
    }
    writeEmployees(items.map((e) => (e.id === next.id ? next : e)));
    return HttpResponse.json(next);
  }),
];
