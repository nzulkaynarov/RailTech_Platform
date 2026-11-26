import { HttpResponse, http } from "msw";

import type {
  QueueCard,
  Zone,
  ZoneCreate,
  ZonePerson,
  ZoneProblem,
  ZoneSummary,
  ZoneUpdate,
} from "../shared/api/generated/model";
import { companyToday } from "../shared/lib/dates";
import { readEmployees } from "./fixtures/employees";
import { type MockRole, readRoles, rolesOf } from "./fixtures/roles";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки «Зон ответственности» (ЕВ-З; BFF `/admin/responsibility-zones…`). Девять зон — как после миграции CRM: людей нет.
 * Проблемы считаются по фактам, как в CRM: нет ответственного, ответственный или замещающий отключён, срок вышел, у ответственного
 * нет разделов зоны (предупреждение). Хранятся в `localStorage`, как сессия мока; без хранилища — копия в памяти.
 */
const KEY = "rt-pf-mock-zones";

interface Stored {
  id: string;
  code: string;
  name: Zone["name"];
  description: Zone["description"];
  sections: string[];
  responsibleId: string | null;
  deputyId: string | null;
  curatorId: string | null;
  basis: string;
  valid_from: string | null;
  valid_to: string | null;
  active: boolean;
  updated_at: string;
}

type Seed = [string, [string, string, string], [string, string, string], string[]];

const SEEDS: readonly Seed[] = [
  [
    "finance",
    ["Финансы", "Moliya", "Finance"],
    [
      "Счета, оплаты, визы бухгалтера, дебиторка.",
      "Hisoblar, tölovlar, buxgalter vizalari, debitorlik qarzi.",
      "Invoices, payments, accountant visas, receivables.",
    ],
    ["eds.payments", "eds.visa.finance"],
  ],
  [
    "legal",
    ["Право", "Huquq", "Legal"],
    [
      "Визы на договоры, шаблоны, права подписи.",
      "Şartnomalarga vizalar, şablonlar, imzo huquqlari.",
      "Contract visas, templates, signing authority.",
    ],
    ["eds.visa.legal", "eds.signing.manage", "company.settings"],
  ],
  [
    "sales",
    ["Продажи", "Savdo", "Sales"],
    [
      "Заявки, расчёты, КП, обязательства перед клиентом.",
      "Arizalar, hisob-kitoblar, tijorat takliflari, mijoz oldidagi majburiyatlar.",
      "Requests, costings, quotes, commitments to the client.",
    ],
    ["crm.clients", "erp.calc", "eds.drafts"],
  ],
  [
    "first_contact",
    ["Первый контакт", "Birinçi aloqa", "First contact"],
    [
      "Разбор лидов и закрепление за менеджером.",
      "Lidlarni saralaş va menejerga biriktiriş.",
      "Triage of leads and assignment to a manager.",
    ],
    ["crm.leads.triage", "crm.leads", "crm.mail"],
  ],
  [
    "records",
    ["Делопроизводство", "Iş yuritiş", "Records management"],
    [
      "Регистрация, номера, отправка, архив.",
      "Röyxatga oliş, raqamlar, yuboriş, arxiv.",
      "Registration, numbers, dispatch, archive.",
    ],
    ["eds.inbox", "eds.inbox.register", "eds.drafts"],
  ],
  [
    "supply",
    ["Снабжение", "Taʼminot", "Supply"],
    [
      "Закупки, склад, поставщики.",
      "Xaridlar, ombor, yetkazib beruvçilar.",
      "Purchasing, stock, suppliers.",
    ],
    ["erp.stock", "erp.calc.goods"],
  ],
  [
    "projects",
    ["Проекты", "Loyihalar", "Projects"],
    [
      "Этапы, сроки, проблемные проекты.",
      "Bosqiçlar, muddatlar, muammoli loyihalar.",
      "Stages, deadlines, problem projects.",
    ],
    ["eds.projects", "dashboard.queue"],
  ],
  [
    "people",
    ["Люди", "Odamlar", "People"],
    [
      "Приём, отсутствия, замещение, передача дел.",
      "Qabul qiliş, işda yöqlik, almaştiriş, işlarni topşiriş.",
      "Hiring, absences, substitution, handover of cases.",
    ],
    ["admin"],
  ],
  [
    "it_settings",
    ["ИТ и настройки", "IT va sozlamalar", "IT and settings"],
    [
      "Подключения, копии, доступ, состояние.",
      "Ulanişlar, nusxalar, kiriş huquqi, holat.",
      "Connections, backups, access, health.",
    ],
    ["admin", "company.settings"],
  ],
];

function seed(): Stored[] {
  return SEEDS.map(([code, name, description, sections], index) => ({
    id: String(index + 1),
    code,
    name: { ru: name[0], uz: name[1], en: name[2] },
    description: { ru: description[0], uz: description[1], en: description[2] },
    sections,
    responsibleId: null,
    deputyId: null,
    curatorId: null,
    basis: "",
    valid_from: null,
    valid_to: null,
    active: true,
    updated_at: "2026-11-23T09:00:00Z",
  }));
}

let memory: Stored[] | null = null;

function read(): Stored[] {
  if (memory) return memory;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) {
      memory = JSON.parse(raw) as Stored[];
      return memory;
    }
  } catch {
    // Начинаем с зерна.
  }
  memory = seed();
  return memory;
}

function write(items: Stored[]): void {
  memory = items;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetZonesMock(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}

export function readZones(): Stored[] {
  return read();
}

function personOf(id: string | null): ZonePerson | undefined {
  const employee = id ? readEmployees().find((e) => e.id === id) : undefined;
  if (!employee) return undefined;
  return {
    id: employee.id,
    name: employee.name,
    ...(employee.position ? { position: employee.position } : {}),
    active: employee.status === "active",
  };
}

/** Разделы, которых у сотрудника нет даже на чтение (объединение его ролей). */
function missingSections(userId: string, sections: readonly string[]): string[] {
  const employee = readEmployees().find((e) => e.id === userId);
  const held = rolesOf(employee?.role_ids ?? [], readRoles());
  return sections.filter((key) => !held.some((role) => role.access[key] !== undefined));
}

function problemsOf(zone: Stored): ZoneProblem[] {
  if (!zone.active) return [];
  const problems: ZoneProblem[] = [];
  const responsible = personOf(zone.responsibleId);
  if (!responsible) problems.push({ code: "no_responsible", severity: "problem" });
  else if (!responsible.active)
    problems.push({ code: "responsible_inactive", severity: "problem" });
  else {
    const lacking = missingSections(responsible.id, zone.sections);
    if (lacking.length > 0) {
      problems.push({
        code: "responsible_lacks_permissions",
        severity: "warning",
        sections: lacking,
      });
    }
  }
  const deputy = personOf(zone.deputyId);
  if (zone.deputyId && !deputy?.active)
    problems.push({ code: "deputy_inactive", severity: "problem" });
  if (zone.valid_to && zone.valid_to < companyToday()) {
    problems.push({ code: "term_expired", severity: "problem" });
  }
  return problems;
}

function present(zone: Stored): Zone {
  const responsible = personOf(zone.responsibleId);
  const deputy = personOf(zone.deputyId);
  const curator = personOf(zone.curatorId);
  return {
    id: zone.id,
    code: zone.code,
    name: zone.name,
    description: zone.description,
    sections: zone.sections,
    ...(responsible ? { responsible } : {}),
    ...(deputy ? { deputy } : {}),
    ...(curator ? { curator } : {}),
    basis: zone.basis,
    ...(zone.valid_from ? { valid_from: zone.valid_from } : {}),
    ...(zone.valid_to ? { valid_to: zone.valid_to } : {}),
    active: zone.active,
    problems: problemsOf(zone),
    updated_at: zone.updated_at,
  };
}

/** Сводка для сигналов: действующие зоны без действующего ответственного. */
export function zonesSummary(): ZoneSummary {
  const active = read().filter((z) => z.active);
  const withoutResponsible = active.filter((z) =>
    problemsOf(z).some((p) => p.code === "no_responsible" || p.code === "responsible_inactive"),
  );
  return {
    zones_total: active.length,
    without_responsible: withoutResponsible.length,
    with_problems: active.filter((z) => problemsOf(z).length > 0).length,
  };
}

/** Карточка Главной (`GET /queue/cards`): только тем, у кого в «виде» `company.settings: full`, и пока есть зона без ответственного. */
export function zoneCards(view: readonly MockRole[]): QueueCard[] {
  if (!view.some((role) => role.access["company.settings"] === "full")) return [];
  const count = zonesSummary().without_responsible;
  return count > 0
    ? [
        {
          key: "zones_without_responsible",
          label: "Зоны без ответственного",
          count,
          hint: "Настройки · Люди и доступ · Зоны ответственности",
          path: "/admin/zones",
        },
      ]
    : [];
}

function level(resource: string): "full" | "read" | undefined | "no-session" {
  const session = readSession();
  if (!session) return "no-session";
  const me = buildMe(session);
  if (!me) return "no-session";
  return me.resources[resource];
}

const failure = (
  status: number,
  code: string,
  message: string,
  details?: Record<string, unknown>,
) =>
  HttpResponse.json({ code, message, source: "bff", ...(details ? { details } : {}) }, { status });

/** Как у BFF: нет сессии — 401, нет раздела — 403 (`need`: `read` — любое чтение, `full` — изменение). */
function guard(resource: string, need: "read" | "full") {
  const have = level(resource);
  if (have === "no-session") return failure(401, "SESSION_EXPIRED", "Сессия истекла.");
  if (!have || (need === "full" && have !== "full")) {
    return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
  }
  return null;
}

const invalid = (...fields: string[]) =>
  failure(422, "VALIDATION_FAILED", "Проверьте поля.", { fields });

function find(id: string): Stored | undefined {
  return read().find((z) => z.id === id);
}

function save(next: Stored): void {
  write(read().map((z) => (z.id === next.id ? next : z)));
}

export const zonesHandlers = [
  http.get("*/admin/responsibility-zones/summary", () => {
    const denied = guard("company.settings", "full");
    return denied ?? HttpResponse.json(zonesSummary());
  }),

  http.get("*/admin/responsibility-zones", () => {
    const denied = guard("admin", "read");
    return denied ?? HttpResponse.json({ items: read().map(present) });
  }),

  http.post("*/admin/responsibility-zones", async ({ request }) => {
    const denied = guard("admin", "full");
    if (denied) return denied;
    const body = (await request.json()) as ZoneCreate;
    if (read().some((z) => z.code === body.code)) {
      return failure(409, "CONFLICT", "Зона с таким кодом уже есть.");
    }
    const description = { ru: "", uz: "", en: "", ...body.description };
    const created: Stored = {
      id: String(Math.max(0, ...read().map((z) => Number(z.id))) + 1),
      code: body.code,
      name: body.name,
      description,
      sections: body.sections,
      responsibleId: null,
      deputyId: null,
      curatorId: null,
      basis: "",
      valid_from: null,
      valid_to: null,
      active: true,
      updated_at: new Date().toISOString(),
    };
    write([...read(), created]);
    return HttpResponse.json(present(created), { status: 201 });
  }),

  http.get("*/admin/responsibility-zones/:id", ({ params }) => {
    const denied = guard("admin", "read");
    if (denied) return denied;
    const zone = find(String(params["id"]));
    return zone ? HttpResponse.json(present(zone)) : failure(404, "NOT_FOUND", "Зоны нет.");
  }),

  http.patch("*/admin/responsibility-zones/:id", async ({ params, request }) => {
    const denied = guard("company.settings", "full");
    if (denied) return denied;
    const zone = find(String(params["id"]));
    if (!zone) return failure(404, "NOT_FOUND", "Зоны нет.");
    if (!zone.active) return failure(409, "CONFLICT", "Зона выключена.");
    const body = (await request.json()) as ZoneUpdate;
    const next: Stored = { ...zone };
    const people: [keyof ZoneUpdate, "responsibleId" | "deputyId" | "curatorId"][] = [
      ["responsible_id", "responsibleId"],
      ["deputy_id", "deputyId"],
      ["curator_id", "curatorId"],
    ];
    for (const [field, target] of people) {
      if (!(field in body)) continue;
      const id = body[field];
      if (id && !personOf(id)?.active) return invalid(field);
      next[target] = id ?? null;
    }
    if (next.responsibleId && next.responsibleId === next.deputyId) return invalid("deputy_id");
    if ("basis" in body) next.basis = (body.basis ?? "").trim();
    if ("valid_from" in body) next.valid_from = body.valid_from ?? null;
    if ("valid_to" in body) next.valid_to = body.valid_to ?? null;
    if (next.valid_from && next.valid_to && next.valid_from > next.valid_to) {
      return invalid("valid_to");
    }
    next.updated_at = new Date().toISOString();
    save(next);
    return HttpResponse.json(present(next));
  }),

  http.post("*/admin/responsibility-zones/:id/deactivate", ({ params }) => toggle(params, false)),
  http.post("*/admin/responsibility-zones/:id/activate", ({ params }) => toggle(params, true)),
];

function toggle(params: Record<string, string | readonly string[] | undefined>, active: boolean) {
  const denied = guard("admin", "full");
  if (denied) return denied;
  const zone = find(String(params["id"]));
  if (!zone) return failure(404, "NOT_FOUND", "Зоны нет.");
  const next = { ...zone, active, updated_at: new Date().toISOString() };
  save(next);
  return HttpResponse.json(present(next));
}
