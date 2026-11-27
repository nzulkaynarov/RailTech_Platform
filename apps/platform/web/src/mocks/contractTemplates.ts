import { HttpResponse, http } from "msw";

import type {
  ContractTemplate,
  ContractTemplateIn,
  OfferedContractTemplates,
} from "../shared/api/generated/model";
import { buildMe, readSession } from "./mockSession";

/**
 * «Документы · Шаблоны · Договоры» (ДОК-10) на моках: четыре шаблона как на макете (доска 39). Состояние в памяти страницы:
 * «Новая редакция» делает черновик-копию, «На утверждение» — статус «На утверждении», «Утвердить» — только у держателя зоны
 * «Право» (раздел `eds.visa.legal`) или администратора; прежняя утверждённая редакция снимается с показа.
 */
const seed = (): ContractTemplate[] => [
  {
    id: "1",
    name: "Договор с клиентом · поставка",
    edition: 3,
    status: "approved",
    counterparty: "client",
    subject: "supply",
    approved_by: "А. Юсупов",
    approved_at: "2026-11-20T10:00:00+05:00",
    submitted_at: "2026-11-19T10:00:00+05:00",
    is_active: true,
    locked: true,
    languages: ["ru"],
    base_role: null,
    unknown_placeholders: [],
    updated_at: "2026-11-20T10:00:00+05:00",
  },
  {
    id: "2",
    name: "Договор с партнёром · поставка",
    edition: 2,
    status: "approved",
    counterparty: "partner",
    subject: "supply",
    approved_by: "А. Юсупов",
    approved_at: "2026-11-18T10:00:00+05:00",
    submitted_at: "2026-11-17T10:00:00+05:00",
    is_active: true,
    locked: true,
    languages: ["ru"],
    base_role: "partnership",
    unknown_placeholders: [],
    updated_at: "2026-11-18T10:00:00+05:00",
  },
  {
    id: "3",
    name: "Договор с клиентом · услуги",
    edition: 1,
    status: "on_approval",
    counterparty: "client",
    subject: "services",
    approved_by: null,
    approved_at: null,
    submitted_at: "2026-11-22T10:00:00+05:00",
    is_active: false,
    locked: true,
    languages: ["ru"],
    base_role: null,
    unknown_placeholders: [],
    updated_at: "2026-11-22T10:00:00+05:00",
  },
  {
    id: "4",
    name: "Договор с партнёром · услуги",
    edition: 1,
    status: "draft",
    counterparty: "partner",
    subject: "services",
    approved_by: null,
    approved_at: null,
    submitted_at: null,
    is_active: false,
    locked: false,
    languages: ["ru"],
    base_role: null,
    unknown_placeholders: [],
    updated_at: "2026-11-21T10:00:00+05:00",
  },
];

let templates = seed();
export const resetContractTemplates = (): void => {
  templates = seed();
};

const unauthorized = () =>
  HttpResponse.json(
    { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
    { status: 401 },
  );

const refusal = (status: number, reason: string, message: string) =>
  HttpResponse.json(
    {
      code: status === 403 ? "FORBIDDEN" : "CONFLICT",
      message,
      source: "erp",
      details: { backend_status: status, reason },
    },
    { status },
  );

function change(id: string, apply: (row: ContractTemplate) => ContractTemplate | null) {
  const row = templates.find((r) => r.id === id);
  if (!row)
    return HttpResponse.json({ code: "NOT_FOUND", message: "Не найдено." }, { status: 404 });
  const next = apply(row);
  if (!next) {
    return refusal(409, "template_transition_not_allowed", "Шаблон сейчас в другом статусе.");
  }
  return HttpResponse.json(next);
}

function mayApprove(): boolean {
  const session = readSession();
  if (!session) return false;
  const me = buildMe(session);
  if (!me) return false;
  return me.resources["eds.visa.legal"] === "full" || me.resources["admin"] === "full";
}

export const contractTemplatesHandlers = [
  http.get("*/api/v1/document-templates/contracts/offered", () => {
    if (!readSession()) return unauthorized();
    const items = templates.filter(
      (r) => r.status === "approved" && r.is_active && r.counterparty === "client",
    );
    const body: OfferedContractTemplates = {
      counterparty: "client",
      default_id: items[0]?.id ?? null,
      items,
    };
    return HttpResponse.json(body);
  }),
  http.get("*/api/v1/document-templates/contracts", () => {
    if (!readSession()) return unauthorized();
    return HttpResponse.json({ items: templates });
  }),
  http.post("*/api/v1/document-templates/contracts", async ({ request }) => {
    if (!readSession()) return unauthorized();
    const body = (await request.json()) as ContractTemplateIn;
    const row: ContractTemplate = {
      id: String(templates.length + 1),
      name: body.name.trim(),
      edition: 1,
      status: "draft",
      counterparty: body.counterparty,
      subject: body.subject,
      approved_by: null,
      approved_at: null,
      submitted_at: null,
      is_active: false,
      locked: false,
      languages: ["ru"],
      base_role: body.base_role ?? null,
      unknown_placeholders: [],
      updated_at: new Date().toISOString(),
    };
    templates = [...templates, row];
    return HttpResponse.json(row, { status: 201 });
  }),
  http.patch("*/api/v1/document-templates/contracts/:id/base-role", async ({ params, request }) => {
    if (!readSession()) return unauthorized();
    const body = (await request.json()) as { base_role: ContractTemplate["base_role"] };
    return change(String(params["id"]), (row) => {
      if (row.locked) return null;
      const next: ContractTemplate = { ...row, base_role: body.base_role };
      templates = templates.map((r) => (r.id === row.id ? next : r));
      return next;
    });
  }),
  http.post("*/api/v1/document-templates/contracts/:id/new-edition", ({ params }) => {
    const source = templates.find((r) => r.id === params["id"]);
    if (!source || source.status !== "approved") {
      return refusal(409, "template_transition_not_allowed", "Шаблон сейчас в другом статусе.");
    }
    const row: ContractTemplate = {
      ...source,
      id: String(templates.length + 1),
      edition: source.edition + 1,
      status: "draft",
      approved_by: null,
      approved_at: null,
      submitted_at: null,
      is_active: false,
      locked: false,
      updated_at: new Date().toISOString(),
    };
    templates = [...templates, row];
    return HttpResponse.json(row, { status: 201 });
  }),
  http.post("*/api/v1/document-templates/contracts/:id/submit", ({ params }) =>
    change(String(params["id"]), (row) => {
      if (row.status !== "draft") return null;
      const next: ContractTemplate = {
        ...row,
        status: "on_approval",
        locked: true,
        submitted_at: new Date().toISOString(),
      };
      templates = templates.map((r) => (r.id === row.id ? next : r));
      return next;
    }),
  ),
  http.post("*/api/v1/document-templates/contracts/:id/approve", ({ params }) => {
    if (!mayApprove()) return refusal(403, "template_approval_forbidden", "Утверждает «Право».");
    return change(String(params["id"]), (row) => {
      if (row.status !== "on_approval") return null;
      const next: ContractTemplate = {
        ...row,
        status: "approved",
        is_active: true,
        approved_by: "Демо Директоров",
        approved_at: new Date().toISOString(),
      };
      templates = templates.map((r) =>
        r.id === row.id
          ? next
          : r.name === row.name && r.status === "approved"
            ? { ...r, is_active: false }
            : r,
      );
      return next;
    });
  }),
  http.post("*/api/v1/document-templates/contracts/:id/return-to-draft", ({ params }) => {
    if (!mayApprove()) return refusal(403, "template_approval_forbidden", "Утверждает «Право».");
    return change(String(params["id"]), (row) => {
      if (row.status !== "on_approval") return null;
      const next: ContractTemplate = {
        ...row,
        status: "draft",
        locked: false,
        submitted_at: null,
      };
      templates = templates.map((r) => (r.id === row.id ? next : r));
      return next;
    });
  }),
];
