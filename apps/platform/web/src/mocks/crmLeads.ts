import { HttpResponse, http } from "msw";

import type {
  ClientCard,
  ClientInvitation,
  ClientRequestRow,
  EdsFile,
  InvitationResendIn,
  LeadPage,
  RequestCreatedView,
  RequestFileFromMessageIn,
  RequestFormIn,
  RequestRetriedView,
} from "../shared/api/generated/model";
import { failure } from "./adminUsers";
import { parseUploadedFile } from "./edsDocuments";
import { mockFlag } from "./fixtures/messages";
import {
  type LeadMockRow,
  type LeadsMock,
  MOCK_ERP_DOWN_KEY,
  clientRow,
  readLeads,
  writeLeads,
} from "./fixtures/leads";
import { buildMe, currentActor, readSession } from "./mockSession";

/**
 * Моки «Клиенты · Лиды, Клиенты и „Создать заявку“» (D1-2b). Права — как в BFF: лиды — `crm.leads`, клиенты и
 * заявки — `crm.clients`; чтение — от уровня «чтение», изменения — «полный». Отказы формы — коды CRM в `details.reason`
 * (`handoff_no_consent`, `consent_via_bot`, `contact_channel_required`, `request_not_allowed`, `request_not_failed`), чтобы
 * экран и e2e видели настоящее поведение. Повтор формы с тем же `request_key` — 200 с той же заявкой, без второй строки.
 */
type Level = "read" | "full";
type Resource = "crm.leads" | "crm.clients";

const MAX_UPLOAD = 25 * 1024 * 1024;
const ALLOWED_TYPES =
  /^(application\/pdf|image\/|application\/(msword|vnd\.ms-|vnd\.openxmlformats-officedocument\.))/;
const ALLOWED_EXTENSIONS = /\.(pdf|png|jpe?g|gif|webp|tiff?|docx?|xlsx?|pptx?)$/i;

function guard(resource: Resource, need: Level) {
  const session = readSession();
  if (!session) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  const level = buildMe({ ...session, activeRole: null })?.resources[resource];
  if (level === "full" || (need === "read" && level === "read")) return null;
  return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
    resource,
    need,
  });
}

function findLead(state: LeadsMock, lead: string | null | undefined): LeadMockRow | undefined {
  if (!lead) return undefined;
  return state.leads.find((l) => l.row.lead === lead.toUpperCase());
}

const leadNotFound = () => failure(404, "NOT_FOUND", "Лид не найден.", "crm");
const clientNotFound = () => failure(404, "NOT_FOUND", "Клиент не найден.", "crm");

function rejected(status: 409 | 422, reason: string, message: string, fields?: string[]) {
  return failure(status, status === 409 ? "CONFLICT" : "VALIDATION_FAILED", message, "crm", {
    reason,
    ...(fields ? { fields } : {}),
  });
}

function nextNumber(state: LeadsMock): string {
  const number = `ЗВ-2026-${String(state.nextNumber).padStart(3, "0")}`;
  state.nextNumber += 1;
  return number;
}

/** Отказы «Создать заявку» — в том же порядке, что в CRM. */
function validateRequest(body: RequestFormIn, lead: LeadMockRow | undefined): Response | null {
  if (!lead && !body.client_id) {
    return rejected(422, "client_required", "Укажите лида или клиента.", ["client_id"]);
  }
  if (lead?.row.status === "lost") {
    return rejected(409, "request_not_allowed", "Лид в отказе: заявку создать нельзя.");
  }
  if (lead && !lead.consent) {
    if (!body.consent) {
      return rejected(
        422,
        "handoff_no_consent",
        "Отметьте, как клиент дал согласие на обработку данных.",
      );
    }
    if (lead.row.channel === "telegram") {
      return rejected(
        409,
        "consent_via_bot",
        "Клиент из Telegram даёт согласие в боте — попросите его там.",
      );
    }
  }
  const contact = body.contact;
  const leadTelegram = lead?.row.channel === "telegram" && contact.use_lead_telegram === true;
  if (!contact.contact_id && !contact.phone && !contact.email && !leadTelegram) {
    return rejected(
      422,
      "contact_channel_required",
      "Укажите телефон, почту или Telegram контакта.",
      ["contact"],
    );
  }
  return null;
}

export const crmLeadsHandlers = [
  http.get("*/api/v1/crm/leads", ({ request }) => {
    const denied = guard("crm.leads", "read");
    if (denied) return denied;
    const url = new URL(request.url);
    const tab = url.searchParams.get("tab") ?? "all";
    const scope = url.searchParams.get("scope") ?? "all";
    const q = (url.searchParams.get("q") ?? "").trim().toLowerCase();
    const channel = url.searchParams.get("channel");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    const limit = Number(url.searchParams.get("limit") ?? "50");
    const me = currentActor()?.id;
    const rows = readLeads()
      .leads.map((l) => l.row)
      .filter((row) => tab === "all" || row.status === tab)
      .filter((row) => scope !== "mine" || (me !== undefined && row.assigned?.id === me))
      .filter((row) => scope !== "overdue" || row.overdue)
      .filter((row) => !channel || row.channel === channel)
      .filter(
        (row) =>
          !q || row.name.toLowerCase().includes(q) || (row.need ?? "").toLowerCase().includes(q),
      )
      .sort((a, b) => (b.last_message_at ?? "").localeCompare(a.last_message_at ?? ""));
    const page: LeadPage = { items: rows.slice(offset, offset + limit), total: rows.length };
    return HttpResponse.json(page);
  }),

  http.get("*/api/v1/crm/leads/:lead", ({ params }) => {
    const denied = guard("crm.leads", "read");
    if (denied) return denied;
    const lead = findLead(readLeads(), String(params["lead"]));
    return lead ? HttpResponse.json(lead.card) : leadNotFound();
  }),

  http.get("*/api/v1/crm/clients", ({ request }) => {
    const denied = guard("crm.clients", "read");
    if (denied) return denied;
    const q = (new URL(request.url).searchParams.get("q") ?? "").trim().toLowerCase();
    const items = readLeads()
      .clients.filter((c) => !q || c.name.toLowerCase().includes(q) || (c.inn ?? "").includes(q))
      .map(clientRow);
    return HttpResponse.json({ items });
  }),

  http.get("*/api/v1/crm/clients/:id", ({ params }) => {
    const denied = guard("crm.clients", "read");
    if (denied) return denied;
    const client = readLeads().clients.find((c) => c.id === Number(params["id"]));
    return client ? HttpResponse.json(client) : clientNotFound();
  }),

  http.post("*/api/v1/crm/clients/:id/invitation", async ({ request, params }) => {
    const denied = guard("crm.clients", "full");
    if (denied) return denied;
    const state = readLeads();
    const client = state.clients.find((c) => c.id === Number(params["id"]));
    if (!client) return clientNotFound();
    const body = (await request.json()) as InvitationResendIn;
    const via =
      body.channel === "both" ? (["email", "telegram"] as const) : ([body.channel] as const);
    const contact =
      client.contacts.find((c) => c.id === body.contact_id) ??
      client.contacts.find((c) => c.is_primary) ??
      client.contacts[0];
    const reachable = via.filter((channel) => contact?.channels.includes(channel));
    // Канал недоступен — итог `failed` словами, не ошибка запроса (как в CRM).
    const invitation: ClientInvitation = {
      status: reachable.length ? "sent" : "failed",
      channel: body.channel,
      sent_via: [...reachable],
      sent_at: reachable.length ? new Date().toISOString() : null,
      contact_name: contact?.name ?? null,
      error_text: reachable.length ? null : "У контакта нет такого канала связи.",
      available_channels: ["email", "telegram", "both"],
      suggested_channel: client.invitation?.suggested_channel ?? "email",
      can_resend: true,
    };
    client.invitation = invitation;
    writeLeads(state);
    return HttpResponse.json(invitation);
  }),

  http.post("*/api/v1/crm/requests", async ({ request }) => {
    const denied = guard("crm.clients", "full");
    if (denied) return denied;
    const body = (await request.json()) as RequestFormIn;
    const state = readLeads();
    const repeat = state.keys[body.request_key];
    if (repeat !== undefined) {
      const client = state.clients.find((c) => c.requests.some((r) => r.deal === repeat));
      const row = client?.requests.find((r) => r.deal === repeat);
      if (client && row) {
        const again: RequestCreatedView = {
          client_id: client.id,
          deal: repeat,
          lead: body.lead ?? null,
          created: false,
          transfer: row.transfer ?? "done",
        };
        return HttpResponse.json(again);
      }
    }
    const lead = findLead(state, body.lead);
    if (body.lead && !lead) return leadNotFound();
    const invalid = validateRequest(body, lead);
    if (invalid) return invalid;

    let client: ClientCard | undefined;
    const clientId = body.client_id ?? lead?.row.client_id;
    if (clientId) {
      client = state.clients.find((c) => c.id === clientId);
      if (!client) return clientNotFound();
    } else {
      state.nextClient += 1;
      client = {
        id: state.nextClient,
        name: body.company?.name ?? lead?.card.contacts.company ?? lead?.row.name ?? "Новый клиент",
        inn: body.company?.inn ?? null,
        segment: null,
        in_erp: false,
        handoff: { status: "pending", error: null },
        contacts: [],
        leads: [],
        requests: [],
        documents: [],
        invitation: null,
        sources: { contacts: "ok", requests: "ok", documents: "ok" },
      };
      state.clients.push(client);
    }
    if (!body.contact.contact_id && body.contact.full_name) {
      const telegram = body.contact.use_lead_telegram
        ? (lead?.card.contacts.telegram ?? null)
        : null;
      const channels = [
        ...(telegram ? (["telegram"] as const) : []),
        ...(body.contact.phone ? (["phone"] as const) : []),
        ...(body.contact.email ? (["email"] as const) : []),
      ];
      client.contacts.push({
        id: client.id * 10 + client.contacts.length + 1,
        name: body.contact.full_name,
        position: body.contact.position ?? null,
        phone: body.contact.phone ?? null,
        email: body.contact.email ?? null,
        telegram,
        channels,
        preferred_channel: telegram ? "telegram" : body.contact.email ? "email" : null,
        is_primary: client.contacts.length === 0,
      });
    }

    // Упрощение мока: передача в ERP завершается сразу (в CRM — фоновая задача и событие шины). ERP «упала» — флаг
    // `rt-pf-mock-erp-down`: заявка остаётся без номера с `transfer: failed`, её поднимает «Повторить».
    const erpDown = mockFlag(MOCK_ERP_DOWN_KEY);
    state.nextDeal += 1;
    const now = new Date().toISOString();
    const row: ClientRequestRow = {
      deal: state.nextDeal,
      number: erpDown ? null : nextNumber(state),
      title: `Заявка: ${client.name}`,
      summary: body.summary,
      step: "REQUEST",
      project: false,
      client_sees: "in_work",
      urgency: body.urgency,
      transfer: erpDown ? "failed" : "done",
      transfer_error: erpDown ? "erp_unavailable" : null,
      created_at: now,
      letter_file_id: body.letter_file_id ?? null,
    };
    client.requests.unshift(row);
    if (!erpDown) {
      client.in_erp = true;
      client.handoff = { status: "done", error: null };
    }
    if (lead) {
      lead.row.status = "client";
      lead.row.client_id = client.id;
      lead.card.status = "client";
      lead.card.client = { id: client.id, name: client.name, inn: client.inn };
      if (!client.leads.some((l) => l.lead === lead.row.lead)) {
        client.leads.push({
          lead: lead.row.lead,
          name: lead.row.name,
          status: "client",
          last_message_at: lead.row.last_message_at,
        });
      }
    }
    state.keys[body.request_key] = row.deal;
    writeLeads(state);
    const created: RequestCreatedView = {
      client_id: client.id,
      deal: row.deal,
      lead: lead?.row.lead ?? null,
      created: true,
      transfer: erpDown ? "failed" : "done",
    };
    return HttpResponse.json(created, { status: 201 });
  }),

  http.post("*/api/v1/crm/requests/:deal/retry", ({ params }) => {
    const denied = guard("crm.clients", "full");
    if (denied) return denied;
    const deal = Number(params["deal"]);
    const state = readLeads();
    const client = state.clients.find((c) => c.requests.some((r) => r.deal === deal));
    const row = client?.requests.find((r) => r.deal === deal);
    if (!client || !row) return failure(404, "NOT_FOUND", "Заявка не найдена.", "crm");
    if (row.transfer !== "failed") {
      return rejected(409, "request_not_failed", "Заявка уже передана в ERP.");
    }
    row.transfer = "done";
    row.transfer_error = null;
    row.number = nextNumber(state);
    client.in_erp = true;
    client.handoff = { status: "done", error: null };
    writeLeads(state);
    const retried: RequestRetriedView = { deal, client_id: client.id, transfer: "done" };
    return HttpResponse.json(retried);
  }),

  http.post("*/api/v1/crm/request-files", async ({ request }) => {
    const denied = guard("crm.clients", "full");
    if (denied) return denied;
    const file = await parseUploadedFile(request);
    if (file === null) {
      return failure(422, "VALIDATION_FAILED", "Файл нужно передать формой multipart.", "bff", {
        fields: ["file"],
      });
    }
    if (file.size > MAX_UPLOAD) {
      return failure(413, "PAYLOAD_TOO_LARGE", "Файл больше 25 МБ.", "bff", {
        max_bytes: MAX_UPLOAD,
      });
    }
    if (!ALLOWED_TYPES.test(file.type) && !ALLOWED_EXTENSIONS.test(file.name)) {
      return failure(
        415,
        "UNSUPPORTED_MEDIA_TYPE",
        "Допустимы PDF, изображения и документы Office.",
        "bff",
      );
    }
    const stored: EdsFile = {
      id: crypto.randomUUID(),
      name: file.name,
      content_type: file.type || "application/octet-stream",
      size: file.size,
    };
    return HttpResponse.json(stored, { status: 201 });
  }),

  http.post("*/api/v1/crm/request-files/from-message", async ({ request }) => {
    const denied = guard("crm.leads", "read") ?? guard("crm.clients", "full");
    if (denied) return denied;
    const body = (await request.json()) as RequestFileFromMessageIn;
    if (!body.lead)
      return failure(422, "VALIDATION_FAILED", "Укажите сообщение лида.", "bff", {
        fields: ["lead"],
      });
    const stored: EdsFile = {
      id: crypto.randomUUID(),
      name: "письмо-директору.pdf",
      content_type: "application/pdf",
      size: 184_320,
    };
    return HttpResponse.json(stored, { status: 201 });
  }),
];
