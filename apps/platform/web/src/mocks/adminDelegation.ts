import { HttpResponse, http } from "msw";

import type {
  DelegationCatalog,
  EmployeeDelegation,
  EmployeeDelegationUpdate,
} from "../shared/api/generated/model";
import { accessFor, readEmployees, writeEmployees } from "./fixtures/employees";
import { readRoles, writeRoles } from "./fixtures/roles";
import { failure, guard } from "./adminUsers";

type Grants = Record<string, "full" | "read">;
const LABELS = (ru: string, uz: string, en: string) => ({ ru, uz, en });

/** Часть действий каталога `platform-rbac-capabilities.yaml` — достаточно для экранов и тестов. */
const ACTIONS: { code: string; area: string; label: ReturnType<typeof LABELS>; grants: Grants }[] =
  [
    {
      code: "leads.work",
      area: "sales",
      label: LABELS(
        "Вести лиды и клиентов",
        "Lidlar va mijozlar bilan işlaş",
        "Work leads and clients",
      ),
      grants: { "crm.leads": "full", "crm.clients": "full" },
    },
    {
      code: "quote.prepare",
      area: "sales",
      label: LABELS(
        "Готовить расчёт и КП",
        "Hisob-kitob va TT tayyorlaş",
        "Prepare calculations and quotes",
      ),
      grants: { "erp.calc": "full" },
    },
    {
      code: "quote.approve",
      area: "sales",
      label: LABELS(
        "Утверждать и отправлять КП",
        "TT ni tasdiqlaş va yuboriş",
        "Approve and send quotes",
      ),
      grants: { "eds.drafts": "full" },
    },
    {
      code: "inbox.register",
      area: "documents",
      label: LABELS("Регистрировать письма", "Xatlarni röyxatga oliş", "Register letters"),
      grants: { "eds.inbox.register": "full" },
    },
    {
      code: "inbox.resolve",
      area: "documents",
      label: LABELS("Накладывать резолюции", "Rezolyutsiya qöyiş", "Put resolutions"),
      grants: { "eds.inbox": "full" },
    },
    {
      code: "projects.work",
      area: "documents",
      label: LABELS(
        "Вести договоры и проекты",
        "Shartnoma va loyihalarni yuritiş",
        "Handle contracts and projects",
      ),
      grants: { "eds.projects": "full" },
    },
    {
      code: "payments.confirm",
      area: "money",
      label: LABELS("Подтверждать оплату", "Tölovni tasdiqlaş", "Confirm payments"),
      grants: { "eds.payments": "full" },
    },
    {
      code: "stock.work",
      area: "purchasing",
      label: LABELS(
        "Вести каталог и закупки",
        "Katalog va xaridlarni yuritiş",
        "Handle catalog and purchasing",
      ),
      grants: { "erp.stock": "full" },
    },
    {
      code: "chats.internal",
      area: "work",
      label: LABELS(
        "Писать коллегам и вести свои задачи",
        "Hamkasblarga yoziş",
        "Message colleagues and keep own tasks",
      ),
      grants: { "chats.internal": "full", "dashboard.queue": "full" },
    },
    {
      code: "admin.staff",
      area: "admin",
      label: LABELS(
        "Управлять сотрудниками и делегированием",
        "Xodimlar va vakolatlarni boshqariş",
        "Manage employees and delegation",
      ),
      grants: { admin: "full" },
    },
    {
      code: "admin.view",
      area: "admin",
      label: LABELS(
        "Смотреть настройки и журнал",
        "Sozlamalar va jurnalni köriş",
        "View settings and the log",
      ),
      grants: { admin: "read" },
    },
  ];
const AREAS = [
  { code: "sales", label: LABELS("Продажи", "Sotuvlar", "Sales") },
  { code: "documents", label: LABELS("Документы", "Hujjatlar", "Documents") },
  { code: "money", label: LABELS("Деньги", "Pul", "Money") },
  {
    code: "purchasing",
    label: LABELS("Закупки и склад", "Xaridlar va ombor", "Purchasing and stock"),
  },
  { code: "work", label: LABELS("Работа", "Iş", "Work") },
  { code: "admin", label: LABELS("Администрирование", "Administratsiya", "Administration") },
];
const RANK = { read: 1, full: 2 } as const;

const rank = (level: "full" | "read" | undefined): number => (level ? RANK[level] : 0);

function codesOn(access: Partial<Record<string, "full" | "read">>): string[] {
  return ACTIONS.filter((a) =>
    Object.entries(a.grants).every(([key, level]) => rank(access[key]) >= RANK[level]),
  ).map((a) => a.code);
}

const saved = new Map<string, string[]>();

function accessOfRoles(roleIds: string[]): Partial<Record<string, "full" | "read">> {
  const merged: Partial<Record<string, "full" | "read">> = {};
  for (const role of readRoles().filter((r) => roleIds.includes(r.id))) {
    for (const [key, level] of Object.entries(role.access)) {
      if (level && rank(level) > rank(merged[key])) merged[key] = level;
    }
  }
  return merged;
}

export const adminDelegationHandlers = [
  http.get("*/admin/delegation", () => {
    const denied = guard("read");
    if (denied) return denied;
    const body: DelegationCatalog = {
      areas: AREAS,
      actions: ACTIONS.map(({ code, area, label }) => ({ code, area, label })),
      presets: readRoles()
        .filter((r) => !r.description.startsWith("personal:"))
        .map((r) => ({ id: r.id, name: r.name, codes: codesOn(accessOfRoles([r.id])) })),
    };
    return HttpResponse.json(body);
  }),
  http.get("*/admin/users/:id/delegation", ({ params }) => {
    const denied = guard("read");
    if (denied) return denied;
    const employee = readEmployees().find((e) => e.id === params["id"]);
    if (!employee) return failure(404, "NOT_FOUND", "Сотрудник не найден");
    const body: EmployeeDelegation = {
      codes: saved.get(employee.id) ?? codesOn(accessOfRoles(employee.role_ids)),
    };
    return HttpResponse.json(body);
  }),
  http.put("*/admin/users/:id/delegation", async ({ params, request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const employee = readEmployees().find((e) => e.id === params["id"]);
    if (!employee) return failure(404, "NOT_FOUND", "Сотрудник не найден");
    const body = (await request.json()) as EmployeeDelegationUpdate;
    // как BFF: личный набор — роль «personal:<id>»; разделы вне каталога действий переносятся
    const covered = new Set(ACTIONS.flatMap((a) => Object.keys(a.grants)));
    const access: Partial<Record<string, "full" | "read">> = {};
    for (const [key, level] of Object.entries(accessOfRoles(employee.role_ids))) {
      if (!covered.has(key)) access[key] = level;
    }
    for (const action of ACTIONS.filter((a) => body.codes.includes(a.code))) {
      for (const [key, level] of Object.entries(action.grants)) {
        if (rank(level) > rank(access[key])) access[key] = level;
      }
    }
    const roles = readRoles();
    const marker = `personal:${employee.id}`;
    const personal = roles.find((r) => r.description === marker);
    const next = {
      id: personal?.id ?? `p-${employee.id}`,
      name: `${employee.position ?? "Личный набор"} · ${employee.name}`,
      description: marker,
      system: false,
      version: (personal?.version ?? 0) + 1,
      access,
      restricted_fields: [],
      updated_at: new Date().toISOString(),
    };
    writeRoles([...roles.filter((r) => r.id !== next.id), next]);
    writeEmployees(
      readEmployees().map((e) =>
        e.id === employee.id ? { ...e, role_ids: [next.id], access: accessFor([next.id]) } : e,
      ),
    );
    saved.set(employee.id, body.codes);
    return HttpResponse.json({ codes: body.codes } satisfies EmployeeDelegation);
  }),
];

export function resetDelegationMock(): void {
  saved.clear();
}
