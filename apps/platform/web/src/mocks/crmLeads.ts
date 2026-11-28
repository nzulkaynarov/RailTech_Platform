import { HttpResponse, http } from "msw";

import type {
  CallNoteView,
  ClientCard,
  ClientInvitation,
  ClientRequestRow,
  EdsFile,
  InvitationResendIn,
  LeadCreated,
  LeadIn,
  LeadPage,
  PartnerHandoffIn,
  PartnerHandoffView,
  PeopleLead,
  PeopleLeadContacts,
  RequestCallNoteIn,
  RequestCreatedView,
  RequestFileFromMessageIn,
  RequestFormIn,
  RequestRetriedView,
} from "../shared/api/generated/model";
import { failure } from "./adminUsers";
import { parseUploadedFile } from "./edsDocuments";
import { readCompanyMock } from "./fixtures/company";
import { mockFlag } from "./fixtures/messages";
import {
  type LeadMockRow,
  type LeadsMock,
  MOCK_ERP_DOWN_KEY,
  clientRow,
  lead as buildLead,
  readLeads,
  writeLeads,
} from "./fixtures/leads";
import { buildMe, currentActor, readSession } from "./mockSession";
import { initialsOf } from "./profileStore";
import { logoUrlOf } from "./pictures";
import { roleStatesOf } from "./notClient";
import { markOf } from "./doNotWorkMarks";
import { inScope, isTest } from "./testMarks";

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
  const level = buildMe(session)?.resources[resource];
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

function rejected(
  status: 409 | 422,
  reason: string,
  message: string,
  fields?: string[],
  extra: Record<string, unknown> = {},
) {
  return failure(status, status === 409 ? "CONFLICT" : "VALIDATION_FAILED", message, "crm", {
    reason,
    ...(fields ? { fields } : {}),
    ...extra,
  });
}

function nextNumber(state: LeadsMock): string {
  const number = `RQ-2026-${String(state.nextNumber).padStart(3, "0")}`;
  state.nextNumber += 1;
  return number;
}

/** Отказы «Создать заявку» — в том же порядке, что в CRM. */
function validateRequest(body: RequestFormIn, lead: LeadMockRow | undefined): Response | null {
  // ВХОД-1: компания без лида и без карточки клиента (письмо) — клиента заводит сама заявка
  if (!lead && !body.client_id && !body.company) {
    return rejected(422, "client_required", "Укажите клиента или компанию.", ["client_id"]);
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
  // «Люди» (PL-1): лиды, ещё не ставшие клиентами; проигранные — только с `closed=true`; значения контактов — по «Показать»
  http.get("*/api/v1/people/leads", ({ request }) => {
    const denied = guard("crm.leads", "read");
    if (denied) return denied;
    const closed = new URL(request.url).searchParams.get("closed") === "true";
    const items: PeopleLead[] = readLeads()
      .leads.filter(({ row }) => row.status !== "client" && (closed || row.status !== "lost"))
      .filter(({ row }) => row.channel !== "cabinet")
      .map(({ row, card }) => ({
        lead: row.lead,
        name: row.name,
        company: card.contacts.company,
        status: row.status,
        channel: row.channel,
        language: row.language,
        assigned: row.assigned,
        need: row.need,
        has_phone: card.contacts.phone !== null,
        has_email: card.contacts.email !== null,
        has_telegram: card.contacts.telegram !== null,
      }));
    return HttpResponse.json({ items, total: items.length });
  }),
  http.post("*/api/v1/people/leads/:lead/reveal", ({ params }) => {
    const denied = guard("crm.leads", "read");
    if (denied) return denied;
    const found = findLead(readLeads(), String(params.lead));
    if (!found) return leadNotFound();
    const body: PeopleLeadContacts = {
      lead: found.row.lead,
      phone: found.card.contacts.phone,
      email: found.card.contacts.email,
      telegram: found.card.contacts.telegram
        ? `@${found.card.contacts.telegram.replace(/^@/, "")}`
        : null,
    };
    return HttpResponse.json(body);
  }),
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
      .leads.filter((l) => !l.card.discarded && l.card.partner_application == null)
      .map((l) => l.row)
      .filter((row) => tab === "all" || row.status === tab)
      .filter((row) => scope !== "mine" || (me !== undefined && row.assigned?.id === me))
      .filter((row) => scope !== "overdue" || row.overdue)
      .filter((row) => !channel || row.channel === channel)
      .filter(
        (row) =>
          !q || row.name.toLowerCase().includes(q) || (row.need ?? "").toLowerCase().includes(q),
      )
      .sort((a, b) => (b.last_message_at ?? "").localeCompare(a.last_message_at ?? ""));
    // Порядок щелчком по шапке (Х-15): `last_message` по возрастанию, `-last_message` по убыванию; без времени — в конце
    const sort = url.searchParams.get("sort");
    if (sort === "last_message" || sort === "-last_message") {
      const withTime = rows.filter((row) => row.last_message_at);
      const without = rows.filter((row) => !row.last_message_at);
      withTime.sort((a, b) => (a.last_message_at ?? "").localeCompare(b.last_message_at ?? ""));
      if (sort.startsWith("-")) withTime.reverse();
      rows.splice(0, rows.length, ...withTime, ...without);
    }
    const page: LeadPage = { items: rows.slice(offset, offset + limit), total: rows.length };
    return HttpResponse.json(page);
  }),

  // «Создать · Лид» (план 2026-11-12 п. 0.1): как CRM — нужен контакт по каналу, дубль по телефону или почте — 409.
  http.post("*/api/v1/crm/leads", async ({ request }) => {
    const denied = guard("crm.leads", "full");
    if (denied) return denied;
    const body = (await request.json()) as LeadIn;
    const phone = body.phone?.replace(/[^\d+]/g, "") || null;
    const email = body.email?.trim().toLowerCase() || null;
    const missing =
      body.source === "phone" && !phone
        ? "phone"
        : body.source === "email" && !email
          ? "email"
          : !phone && !email
            ? "phone"
            : null;
    if (missing) return rejected(422, "contact_required", "Укажите телефон или почту.", [missing]);
    // CRM проверяет почтовый домен (DNS): такого домена нет — 422 по полю «почта».
    if (email?.endsWith(".invalid")) {
      return rejected(422, "invalid_email", "Такого почтового домена нет.", ["email"], {
        domain_missing: true,
      });
    }
    const state = readLeads();
    const same = state.leads.find(
      (l) =>
        (phone && l.card.contacts.phone?.replace(/[^\d+]/g, "") === phone) ||
        (email && l.card.contacts.email?.toLowerCase() === email),
    );
    if (same) {
      return failure(409, "CONFLICT", "Лид с этим контактом уже есть.", "crm", {
        reason: "lead_exists",
        lead: same.row.lead,
        fields: [phone && same.card.contacts.phone ? "phone" : "email"],
      });
    }
    const id = Math.max(0, ...state.leads.map((l) => Number(l.row.lead.slice(2)))) + 1;
    const actor = currentActor();
    const created = buildLead(Date.now(), {
      id,
      name: body.name,
      status: "dialog",
      channel: body.source,
      need: body.need ?? null,
      minutes: 0,
      consent: false,
      ...(phone ? { phone } : {}),
      ...(email ? { email } : {}),
      ...(body.company ? { company: body.company } : {}),
      ...(actor
        ? { assigned: { id: actor.id, name: actor.name, initials: initialsOf(actor.name) } }
        : {}),
    });
    state.leads.unshift(created);
    writeLeads(state);
    const out: LeadCreated = { lead: created.row.lead };
    return HttpResponse.json(out, { status: 201 });
  }),

  http.get("*/api/v1/crm/leads/:lead", ({ params }) => {
    const denied = guard("crm.leads", "read");
    if (denied) return denied;
    const lead = findLead(readLeads(), String(params["lead"]));
    if (!lead) return leadNotFound();
    const client = lead.card.client;
    return HttpResponse.json(
      client
        ? { ...lead.card, client: { ...client, do_not_work: markOf(String(1000 + client.id)) } }
        : lead.card,
    );
  }),

  http.get("*/api/v1/crm/clients", ({ request }) => {
    const denied = guard("crm.clients", "read");
    if (denied) return denied;
    const query = new URL(request.url).searchParams;
    const q = (query.get("q") ?? "").trim().toLowerCase();
    // ТЕСТ-1: без `test` тестовых компаний в списке нет; `only` — вкладка «Тестовые»
    const items = readLeads()
      .clients.filter((c) => inScope(c.in_erp ? String(1000 + c.id) : null, query.get("test")))
      .filter((c) => !q || c.name.toLowerCase().includes(q) || (c.inn ?? "").includes(q))
      .map((c) => ({
        ...clientRow(c),
        do_not_work: markOf(String(1000 + c.id)) !== null,
        is_test: isTest(String(1000 + c.id)),
        logo_url: c.in_erp ? logoUrlOf(String(1000 + c.id)) : null,
        company_id: c.in_erp ? String(1000 + c.id) : null,
        roles: c.in_erp ? roleStatesOf(String(1000 + c.id)) : null,
      }));
    return HttpResponse.json({ items });
  }),

  http.get("*/api/v1/crm/clients/:id", ({ params }) => {
    const denied = guard("crm.clients", "read");
    if (denied) return denied;
    const client = readLeads().clients.find((c) => c.id === Number(params["id"]));
    return client
      ? HttpResponse.json({
          ...client,
          do_not_work: markOf(String(1000 + client.id)),
          is_test: isTest(String(1000 + client.id)),
        })
      : clientNotFound();
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
    // Канал недоступен — итог `failed` словами, не ошибка запроса (как в CRM). Ушедшее — «в очереди»: письмо ждёт
    // почтовый сервис, Telegram — бота; итог карточка покажет позже (B-MAIL-1).
    const invitation: ClientInvitation = {
      status: reachable.length ? "queued" : "failed",
      channel: body.channel,
      sent_via: [...reachable],
      sent_at: null,
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

  // PART-CRM: решение менеджера по партнёру ERP, похожему на клиента
  http.post("*/api/v1/crm/clients/:id/partner-requests/:request/confirm", ({ params }) => {
    const denied = guard("crm.clients", "full");
    if (denied) return denied;
    const state = readLeads();
    const client = state.clients.find((c) => c.id === Number(params["id"]));
    const found = client?.partner_requests.find((r) => r.id === Number(params["request"]));
    if (!client || !found) return clientNotFound();
    client.partner_requests = client.partner_requests.filter((r) => r.id !== found.id);
    client.in_erp = true;
    writeLeads(state);
    return HttpResponse.json({ client_id: client.id });
  }),

  http.post("*/api/v1/crm/clients/:id/partner-requests/:request/decline", ({ params }) => {
    const denied = guard("crm.clients", "full");
    if (denied) return denied;
    const state = readLeads();
    const client = state.clients.find((c) => c.id === Number(params["id"]));
    const found = client?.partner_requests.find((r) => r.id === Number(params["request"]));
    if (!client || !found) return clientNotFound();
    client.partner_requests = client.partner_requests.filter((r) => r.id !== found.id);
    state.nextClient += 1;
    state.clients.push({
      id: state.nextClient,
      name: found.company_name,
      inn: null,
      segment: null,
      in_erp: true,
      handoff: { status: "done", error: null },
      contacts: [],
      leads: [],
      requests: [],
      documents: [],
      invitation: null,
      partner_requests: [],
      sources: { contacts: "ok", requests: "ok", documents: "ok" },
    });
    writeLeads(state);
    return HttpResponse.json({ client_id: state.nextClient });
  }),

  // РЕЗ-1: режим «Резолюция перед расчётом» — из настройки компании мока
  http.get("*/api/v1/crm/requests/resolution", () => {
    const denied = guard("crm.clients", "full");
    if (denied) return denied;
    const notReady = mockFlag("rt-pf-mock-intake-not-ready");
    return HttpResponse.json({
      mode: readCompanyMock().quote.request_resolution,
      ready: !notReady,
      reason: notReady ? "no_crm_mapping" : null,
    });
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
        partner_requests: [],
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
      cabinet_status: "new",
      urgency: body.urgency,
      transfer: erpDown ? "failed" : "done",
      transfer_error: erpDown ? "erp_unavailable" : null,
      created_at: now,
      letter_file_id: body.letter_file_id,
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
      // КЛИЕНТ-1: карточка лида знает свою заявку (как BFF по сделкам клиента)
      lead.card.request = { deal: row.deal, number: row.number, transfer: row.transfer };
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

  // ЛП-1: «Кто это?» → «Партнёр». Как CRM: повтор по лиду — первая заявка (200), лид закрыт исходом «передан как партнёр»;
  // «учёт не отвечает» (тот же флаг, что у заявки клиента) — 503, лид не тронут.
  http.post("*/api/v1/crm/leads/:lead/partner", async ({ request, params }) => {
    const denied = guard("crm.clients", "full");
    if (denied) return denied;
    const body = (await request.json()) as PartnerHandoffIn;
    const state = readLeads();
    const lead = findLead(state, String(params["lead"]));
    if (!lead) return leadNotFound();
    const key = `partner:${lead.row.lead}`;
    const known = state.keys[key];
    if (known !== undefined) {
      const again: PartnerHandoffView = { lead: lead.row.lead, application: known, created: false };
      return HttpResponse.json(again);
    }
    if (lead.row.status === "lost") {
      return rejected(409, "request_not_allowed", "Лид уже закрыт.");
    }
    if (mockFlag(MOCK_ERP_DOWN_KEY)) {
      return failure(503, "BACKEND_UNAVAILABLE", "Учёт не отвечает.", "erp", {
        reason: "erp_unavailable",
      });
    }
    // Почта не обязательна (ПК-1); если указана, проверяется как в ERP (Django): с чужим форматом заявка не уходит
    if (body.email && !/^[^@\s]+@[^@\s]+\.[a-z0-9-]{2,}$/i.test(body.email)) {
      return rejected(422, "invalid_email", "Проверьте адрес почты.", ["email"]);
    }
    const application =
      7000 + Object.keys(state.keys).filter((k) => k.startsWith("partner:")).length + 1;
    state.keys[key] = application;
    lead.row.status = "lost";
    lead.card.status = "lost";
    lead.card.partner_application = application;
    writeLeads(state);
    const created: PartnerHandoffView = { lead: lead.row.lead, application, created: true };
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

/**
 * Записка о звонке (СЦ-6): как BFF — лид только со звонка и только при согласии (в CRM или отмеченном в форме), без лида —
 * по полям формы. Мок отдаёт готовую записку сразу (в EDS она строится секунды); флаг `rt-pf-mock-no-letterhead` —
 * отвечает 409 `letterhead_missing`.
 */
export const MOCK_NOTE_NO_LETTERHEAD_KEY = "rt-pf-mock-no-letterhead";
const NOTE_FILE = (name: string): EdsFile => ({
  id: crypto.randomUUID(),
  name,
  content_type: "application/pdf",
  size: 41_200,
});
const notes = new Map<string, CallNoteView>();

export const callNoteHandlers = [
  http.post("*/api/v1/crm/request-files/call-note", async ({ request }) => {
    const denied = guard("crm.clients", "full");
    if (denied) return denied;
    const body = (await request.json()) as RequestCallNoteIn;
    let name = `Записка о звонке ${new Date().toISOString().slice(0, 10)}.pdf`;
    if (body.lead) {
      const lead = findLead(readLeads(), body.lead);
      if (!lead) return failure(404, "NOT_FOUND", "Лид не найден.", "crm");
      if (lead.card.consent.given_at === null && !body.consent) {
        return rejected(409, "call_note_no_consent", "Нет согласия клиента.");
      }
      name = `${lead.card.channel === "phone" ? "Записка о звонке" : "Записка о запросе"} ${lead.row.lead}.pdf`;
    } else if (!body.caller) {
      return rejected(422, "caller_required", "Укажите, кто звонил.", ["caller"]);
    }
    if (mockFlag(MOCK_NOTE_NO_LETTERHEAD_KEY)) {
      return rejected(409, "letterhead_missing", "Бланк компании не настроен.");
    }
    const id = crypto.randomUUID();
    const ready: CallNoteView = { id, status: "ready", error: null, file: NOTE_FILE(name) };
    notes.set(id, ready);
    return HttpResponse.json(ready, { status: 202 });
  }),

  http.get("*/api/v1/crm/request-files/call-note/:note", ({ params }) => {
    const denied = guard("crm.clients", "full");
    if (denied) return denied;
    const note = notes.get(String(params["note"]));
    if (!note) return failure(404, "NOT_FOUND", "Записка не найдена.", "eds");
    return HttpResponse.json(note);
  }),

  http.get("*/api/v1/crm/request-files/:file", () => {
    const denied = guard("crm.clients", "full");
    if (denied) return denied;
    return new HttpResponse("%PDF-1.4 demo", {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition":
          "attachment; filename*=UTF-8''%D0%97%D0%B0%D0%BF%D0%B8%D1%81%D0%BA%D0%B0.pdf",
      },
    });
  }),
];
