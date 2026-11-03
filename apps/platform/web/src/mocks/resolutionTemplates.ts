import { HttpResponse, http } from "msw";

import { allows } from "../app/rbac.generated";
import type {
  PersonRef,
  ResolutionTemplate,
  ResolutionTemplateIn,
} from "../shared/api/generated/model";
import { personOf } from "./edsInstructions";
import { buildMe, readSession, sessionRoles } from "./mockSession";

/**
 * Моки шаблонов резолюций (EDS-REG, R2; BFF `/eds/resolution-templates`). Правила — как у EDS: видны общие и свои личные,
 * личный — директору и делопроизводителю, общий — администратору; у «Для сведения» нет ответственного, соисполнителей и
 * срока. Хранятся в `localStorage`, как сессия мока. Шаблоны вымышленные.
 */
const KEY = "rt-pf-mock-resolution-templates";

interface Stored extends Omit<ResolutionTemplate, "editable" | "owner"> {
  ownerId: string | null;
}

function seed(): Stored[] {
  const accountant = personOf("u-demo-accountant");
  return [
    {
      id: "70000000-0000-4000-8000-000000000001",
      name: "Налоговая — ответ бухгалтерии",
      scope: "personal",
      kind: "reply",
      text: "Подготовить ответ в срок, проект — мне на согласование.",
      responsible_type: "person",
      responsible: accountant ?? null,
      co_executors: [],
      acquaint: [],
      due_days: 5,
      ownerId: "u-demo-director",
    },
    {
      id: "70000000-0000-4000-8000-000000000002",
      name: "Банк — к сведению бухгалтерии",
      scope: "company",
      kind: "info",
      text: "Принять к сведению.",
      responsible_type: "none",
      responsible: null,
      co_executors: [],
      acquaint: accountant ? [accountant] : [],
      due_days: null,
      ownerId: null,
    },
  ];
}

let memory: Stored[] | null = null;

function read(): Stored[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as Stored[];
  } catch {
    // Хранилище недоступно — состояние в памяти.
  }
  return memory ?? seed();
}

function write(items: Stored[]): void {
  memory = items;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetResolutionTemplatesMock(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}

export function readResolutionTemplates(): Stored[] {
  return read();
}

function who() {
  const session = readSession();
  if (!session) return null;
  const me = buildMe({ ...session, activeRole: null });
  const user = sessionRoles(session)?.user;
  if (!me || !user) return null;
  const r = me.resources;
  return {
    id: user.id,
    author: allows(r, "eds.inbox", "full") || allows(r, "eds.inbox.register", "full"),
    admin: allows(r, "admin", "full"),
    reader: allows(r, "admin", "read"),
  };
}

const failure = (status: number, code: string, message: string, reason?: string) =>
  HttpResponse.json(
    {
      code,
      message,
      source: status === 403 && !reason ? "bff" : "eds",
      ...(reason ? { details: { reason } } : {}),
    },
    { status },
  );

function present(item: Stored, me: NonNullable<ReturnType<typeof who>>): ResolutionTemplate {
  const { ownerId, ...rest } = item;
  return {
    ...rest,
    owner: ownerId ? (personOf(ownerId) ?? null) : null,
    editable: item.scope === "company" ? me.admin : ownerId === me.id,
  };
}

const people = (ids: readonly string[]): PersonRef[] =>
  ids.flatMap((id) => {
    const found = personOf(id);
    return found ? [found] : [];
  });

function fromBody(body: ResolutionTemplateIn): Omit<Stored, "id" | "ownerId"> {
  const info = body.kind === "info";
  const type = info ? "none" : (body.responsible_type ?? "none");
  return {
    name: body.name.trim(),
    scope: body.scope,
    kind: body.kind,
    text: body.text.trim(),
    responsible_type: type,
    responsible:
      type === "person" && body.responsible_id ? (personOf(body.responsible_id) ?? null) : null,
    co_executors: info ? [] : people(body.co_executor_ids ?? []),
    acquaint: people(body.acquaint_ids ?? []),
    due_days: info ? null : (body.due_days ?? null),
  };
}

function visible(item: Stored, id: string): boolean {
  return item.scope === "company" || item.ownerId === id;
}

export const resolutionTemplatesHandlers = [
  http.get("*/eds/resolution-templates", () => {
    const me = who();
    if (!me) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    if (!me.author && !me.reader)
      return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    const items = read()
      .filter((item) => visible(item, me.id))
      .sort((a, b) =>
        a.scope === b.scope ? a.name.localeCompare(b.name, "ru") : a.scope === "personal" ? -1 : 1,
      );
    return HttpResponse.json({ items: items.map((item) => present(item, me)) });
  }),

  http.post("*/eds/resolution-templates", async ({ request }) => {
    const me = who();
    if (!me) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    const body = (await request.json()) as ResolutionTemplateIn;
    if (body.scope === "company" && !me.admin) {
      return failure(
        403,
        "FORBIDDEN",
        "Общие шаблоны ведёт администратор.",
        "company_template_admin_only",
      );
    }
    if (body.scope === "personal" && !me.author) {
      return failure(
        403,
        "FORBIDDEN",
        "Личные шаблоны — у тех, кто готовит резолюции.",
        "personal_template_not_allowed",
      );
    }
    const ownerId = body.scope === "personal" ? me.id : null;
    const all = read();
    const name = body.name.trim().toLowerCase();
    if (
      all.some(
        (item) =>
          item.scope === body.scope && item.ownerId === ownerId && item.name.toLowerCase() === name,
      )
    ) {
      return failure(409, "CONFLICT", "Шаблон с таким названием уже есть.", "name_taken");
    }
    const created: Stored = { id: crypto.randomUUID(), ownerId, ...fromBody(body) };
    write([...all, created]);
    return HttpResponse.json(present(created, me), { status: 201 });
  }),

  http.put("*/eds/resolution-templates/:id", async ({ params, request }) => {
    const me = who();
    if (!me) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    const all = read();
    const current = all.find((item) => item.id === params["id"] && visible(item, me.id));
    if (!current) return failure(404, "NOT_FOUND", "Шаблон не найден.");
    if (current.scope === "company" && !me.admin) {
      return failure(
        403,
        "FORBIDDEN",
        "Общие шаблоны ведёт администратор.",
        "company_template_admin_only",
      );
    }
    const body = (await request.json()) as ResolutionTemplateIn;
    const next: Stored = { ...current, ...fromBody({ ...body, scope: current.scope }) };
    write(all.map((item) => (item.id === current.id ? next : item)));
    return HttpResponse.json(present(next, me));
  }),

  http.delete("*/eds/resolution-templates/:id", ({ params }) => {
    const me = who();
    if (!me) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    const all = read();
    const current = all.find((item) => item.id === params["id"] && visible(item, me.id));
    if (!current) return failure(404, "NOT_FOUND", "Шаблон не найден.");
    if (current.scope === "company" && !me.admin) {
      return failure(
        403,
        "FORBIDDEN",
        "Общие шаблоны ведёт администратор.",
        "company_template_admin_only",
      );
    }
    write(all.filter((item) => item.id !== current.id));
    return new HttpResponse(null, { status: 204 });
  }),
];
