import { HttpResponse, http } from "msw";

import type {
  AssignLeadIn,
  CloseLeadIn,
  DiscardLeadIn,
  LeadContactsIn,
  LeadContactsSaved,
  LeadDuplicate,
  SnoozeLeadIn,
} from "../shared/api/generated/model";
import { failure } from "./adminUsers";
import { leadManagers } from "./crmMessages";
import { readLeads, writeLeads, type LeadMockRow } from "./fixtures/leads";
import { readMessages, writeMessages, type LeadMock } from "./fixtures/messages";
import { buildMe, currentActor, readSession } from "./mockSession";
import { initialsOf } from "./profileStore";

/**
 * Моки ручек лида (LH-1): закрыть, передать коллеге, отбросить, открыть заново, «Принято к сведению», отложить, правка
 * контактов. Два хранилища — «Ждут ответа» и «Лиды» — меняются вместе, как у CRM один лид. Права — `crm.leads` полный;
 * отказы — коды CRM в `details.reason` (`take_first`, `not_closed`, `invalid_phone`), чтобы экран и e2e видели настоящее.
 */
/** Только для тестов: тела правок контактов, как их увидел BFF (какие поля ушли) */
export const patchBodies: LeadContactsIn[] = [];

export const MOCK_LOST_REASONS = ["Дорого", "Выбрали другого", "Нет бюджета", "Другое"];

function guard() {
  const session = readSession();
  if (!session) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  if (buildMe(session)?.resources["crm.leads"] === "full") return null;
  return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
    resource: "crm.leads",
    need: "full",
  });
}

const notFound = () => failure(404, "NOT_FOUND", "Лид не найден.", "crm");
const ok = () => HttpResponse.json({ id: null, ok: true });

function me() {
  const actor = currentActor();
  const name = actor?.name ?? "Сотрудник";
  return { id: actor?.id ?? "0", name, initials: initialsOf(name) };
}

interface Found {
  number: string;
  leads: ReturnType<typeof readLeads>;
  messages: ReturnType<typeof readMessages>;
  row: LeadMockRow | undefined;
  dialog: LeadMock | undefined;
}

function find(lead: string): Found | null {
  const number = lead.toUpperCase();
  const leads = readLeads();
  const messages = readMessages();
  const row = leads.leads.find((l) => l.row.lead === number);
  const dialog = messages.leads.find((l) => l.item.lead === number);
  return row || dialog ? { number, leads, messages, row, dialog } : null;
}

function save(found: Found): void {
  writeLeads(found.leads);
  writeMessages(found.messages);
}

function setStatus(found: Found, status: LeadMockRow["row"]["status"]): void {
  if (!found.row) return;
  found.row.row.status = status;
  found.row.card.status = status;
}

/** Лид вышел из очереди «Ждут ответа»: бот снова ведёт диалог, передача закрыта. */
function leaveQueue(found: Found): void {
  if (!found.dialog) return;
  found.dialog.hidden = true;
  found.dialog.card.owner_mode = "bot";
  found.dialog.card.handoff = null;
  found.dialog.item.handoff = null;
  if (found.row) {
    found.row.card.handoff = null;
    found.row.row.handoff_open = false;
    found.row.row.overdue = false;
  }
}

/** Телефон как у CRM: международный вид; местный номер без кода — +998 */
function normalizePhone(raw: string): string | null {
  const digits = raw.replace(/[^\d]/g, "");
  if (raw.trim().startsWith("+") && digits.length >= 8) return `+${digits}`;
  if (digits.length === 9) return `+998${digits}`;
  if (digits.startsWith("998") && digits.length === 12) return `+${digits}`;
  return null;
}

export const crmLeadActionsHandlers = [
  http.get("*/api/v1/crm/lead-close-options", () => {
    const denied = guard();
    if (denied) return denied;
    return HttpResponse.json({ lost_reasons: MOCK_LOST_REASONS, won_by_erp: false });
  }),

  http.get("*/api/v1/crm/lead-colleagues", () => {
    const denied = guard();
    if (denied) return denied;
    const self = currentActor()?.id;
    return HttpResponse.json({ items: leadManagers().filter((m) => m.id !== self) });
  }),

  http.post("*/api/v1/crm/messages/:lead/close", async ({ params, request }) => {
    const denied = guard();
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const body = (await request.json()) as CloseLeadIn;
    const assigned = found.dialog?.card.assigned ?? found.row?.card.assigned ?? null;
    if (!assigned) {
      return failure(409, "CONFLICT", "Сначала заберите лида.", "crm", { reason: "take_first" });
    }
    if (assigned.id !== currentActor()?.id) {
      return failure(403, "FORBIDDEN", "Лида ведёт другой сотрудник.", "crm", {
        reason: "not_lead_owner",
      });
    }
    setStatus(found, body.outcome === "won" ? "client" : "lost");
    leaveQueue(found);
    save(found);
    return ok();
  }),

  http.post("*/api/v1/crm/messages/:lead/assign", async ({ params, request }) => {
    const denied = guard();
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const body = (await request.json()) as AssignLeadIn;
    const target = leadManagers().find((m) => m.id === body.user_id);
    if (!target) {
      return failure(422, "VALIDATION_FAILED", "Выберите активного менеджера.", "crm", {
        reason: "inactive_colleague",
        fields: ["user_id"],
      });
    }
    for (const card of [found.dialog?.card, found.row?.card]) if (card) card.assigned = target;
    if (found.dialog) found.dialog.item.assigned = target;
    if (found.row) found.row.row.assigned = target;
    save(found);
    return ok();
  }),

  http.post("*/api/v1/crm/messages/:lead/discard", async ({ params, request }) => {
    const denied = guard();
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const body = (await request.json()) as DiscardLeadIn;
    const assigned = found.dialog?.card.assigned ?? found.row?.card.assigned ?? null;
    if (assigned && assigned.id !== currentActor()?.id) {
      return failure(403, "FORBIDDEN", "Лида ведёт другой сотрудник.", "crm", {
        reason: "not_lead_owner",
      });
    }
    if (body.kind === "duplicate") {
      const target = body.duplicate_of ? find(body.duplicate_of) : null;
      if (!target || target.number === found.number || target.row?.card.discarded) {
        return failure(422, "VALIDATION_FAILED", "Выберите другой лид.", "crm", {
          fields: ["duplicate_of"],
        });
      }
    }
    if (body.kind === "test") {
      // «Тест» обезличен и для экрана больше не существует, как после /delete в боте
      found.leads.leads = found.leads.leads.filter((l) => l.row.lead !== found.number);
      found.messages.leads = found.messages.leads.filter((l) => l.item.lead !== found.number);
      save(found);
      return ok();
    }
    setStatus(found, "lost");
    if (found.row) {
      found.row.card.discarded = body.kind;
      found.row.card.duplicate_of = body.duplicate_of ?? null;
    }
    leaveQueue(found);
    save(found);
    return ok();
  }),

  http.post("*/api/v1/crm/messages/:lead/reopen", ({ params }) => {
    const denied = guard();
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const status = found.row?.row.status;
    if (status !== "lost" && status !== "client") {
      return failure(409, "CONFLICT", "Лид не закрыт.", "bff", { reason: "not_closed" });
    }
    const taker = me();
    setStatus(found, "dialog");
    if (found.row) {
      found.row.card.assigned = taker;
      found.row.row.assigned = taker;
      found.row.card.discarded = null;
      found.row.card.duplicate_of = null;
    }
    if (found.dialog) {
      found.dialog.hidden = false;
      found.dialog.card.assigned = taker;
      found.dialog.item.assigned = taker;
      found.dialog.card.owner_mode = "manager";
    }
    save(found);
    return ok();
  }),

  http.post("*/api/v1/crm/messages/:lead/acknowledge", ({ params }) => {
    const denied = guard();
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found) return notFound();
    const handoff = found.dialog?.item.handoff;
    if (!handoff || handoff.priority !== "info" || handoff.state === "taken") {
      return failure(409, "CONFLICT", "Нет открытой передачи.", "crm", {
        reason: "no_open_handoff",
      });
    }
    leaveQueue(found);
    save(found);
    return ok();
  }),

  http.post("*/api/v1/crm/messages/:lead/snooze", async ({ params, request }) => {
    const denied = guard();
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found?.dialog) return notFound();
    const body = (await request.json()) as SnoozeLeadIn;
    const handoff = found.dialog.item.handoff;
    if (!handoff || handoff.state === "taken") {
      return failure(409, "CONFLICT", "Нет открытой передачи.", "crm", {
        reason: "no_open_handoff",
      });
    }
    const hours = { hour: 1, day: 24, three_days: 72 }[body.period];
    const until = new Date(Date.now() + hours * 3_600_000).toISOString();
    found.dialog.item.handoff = { ...handoff, state: "snoozed", snoozed_until: until };
    found.dialog.card.handoff = found.dialog.item.handoff;
    save(found);
    return ok();
  }),

  http.post("*/api/v1/crm/messages/:lead/unsnooze", ({ params }) => {
    const denied = guard();
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found?.dialog) return notFound();
    const handoff = found.dialog.item.handoff;
    if (handoff?.state !== "snoozed") {
      return failure(409, "CONFLICT", "Нет отложенной передачи.", "crm", {
        reason: "no_open_handoff",
      });
    }
    found.dialog.item.handoff = { ...handoff, state: "open", snoozed_until: null };
    found.dialog.card.handoff = found.dialog.item.handoff;
    save(found);
    return ok();
  }),

  http.patch("*/api/v1/crm/leads/:lead", async ({ params, request }) => {
    const denied = guard();
    if (denied) return denied;
    const found = find(String(params["lead"]));
    if (!found?.row) return notFound();
    const body = (await request.json()) as LeadContactsIn;
    patchBodies.push(body);
    const bad = (reason: string, field: string) =>
      failure(422, "VALIDATION_FAILED", "Проверьте поле.", "crm", { reason, fields: [field] });
    const { card, row } = found.row;
    let phone = card.contacts.phone;
    let email = card.contacts.email;
    if (body.name !== undefined) {
      if (!body.name.trim()) return bad("name_required", "name");
      card.name = body.name.trim();
      row.name = body.name.trim();
    }
    if (body.phone !== undefined) {
      const raw = (body.phone ?? "").trim();
      phone = raw ? normalizePhone(raw) : null;
      if (raw && !phone) return bad("invalid_phone", "phone");
    }
    if (body.email !== undefined) {
      const raw = (body.email ?? "").trim().toLowerCase();
      if (raw && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw)) return bad("invalid_email", "email");
      email = raw || null;
    }
    card.contacts.phone = phone;
    card.contacts.email = email;
    if (body.company !== undefined) card.contacts.company = body.company?.trim() || null;
    const duplicates: LeadDuplicate[] = found.leads.leads
      .filter((l) => l.row.lead !== found.number)
      .flatMap((l) => [
        ...(phone && l.card.contacts.phone === phone
          ? [{ kind: "lead", lead: l.row.lead, client_id: null, name: l.card.name, field: "phone" }]
          : []),
        ...(email && l.card.contacts.email === email
          ? [{ kind: "lead", lead: l.row.lead, client_id: null, name: l.card.name, field: "email" }]
          : []),
      ])
      .map((d) => d as LeadDuplicate);
    if (found.dialog) {
      found.dialog.card.name = card.name;
      found.dialog.item.name = card.name;
      found.dialog.card.contacts = { ...found.dialog.card.contacts, ...card.contacts };
    }
    save(found);
    const out: LeadContactsSaved = { duplicates };
    return HttpResponse.json(out);
  }),
];
