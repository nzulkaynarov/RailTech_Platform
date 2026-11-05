import { HttpResponse, http } from "msw";

import { allows } from "../app/rbac.generated";
import type {
  PersonRef,
  SigningAuthority,
  SigningAuthorityDetail,
  SigningAuthorityIn,
  SigningAuthorityPatch,
  SigningAuthorityStatus,
  SigningJournalEntry,
  SigningRejected,
  SigningResolution,
  SigningResolvedAuthority,
  SignerCandidate,
} from "../shared/api/generated/model";
import { companyToday } from "../shared/lib/dates";
import { personOf } from "./edsInstructions";
import { setSigningKindUsage } from "./dictionaries";
import { buildMe, readSession, sessionRoles } from "./mockSession";

/**
 * Моки «Прав подписи» (SIGN-2; BFF `/eds/signing/…`). Правила — как у EDS: доверенность — номер, дата и срок (не больше трёх
 * лет), приказ — номер и дата, устав — без номера; лимит — сумма и валюта вместе; отозванное менять нельзя; подбор «кто
 * вправе подписать» — лимит, срок, отзыв, валюта (замещение в моке не показывается). Хранятся в `localStorage`, как сессия
 * мока; даты считаются от сегодняшнего дня компании, поэтому «истекает через N дней» всегда видно на экране. Сотрудники и
 * организации вымышленные.
 */
const KEY = "rt-pf-mock-signing";
const EXPIRING_DAYS = 30;
const DAY_MS = 86_400_000;
const ALL_KINDS = ["letter_out", "quote", "contract", "invoice", "act", "memo"];

interface Stored {
  id: string;
  holderId: string;
  kinds: string[];
  limit: { amount: string; currency: string } | null;
  basis: SigningAuthority["basis"];
  basis_number: string | null;
  basis_date: string | null;
  valid_from: string;
  valid_to: string | null;
  vakolat_url: string | null;
  note: string | null;
  file: { name: string; content_type: string; size: number; version: number; at: string } | null;
  revoked: { at: string; byId: string; reason: string } | null;
  createdById: string;
  created_at: string;
  updated_at: string;
  journal: {
    at: string;
    action: SigningJournalEntry["action"];
    byId: string | null;
    comment: string | null;
    changes: SigningJournalEntry["changes"];
    file_name: string | null;
  }[];
}

function shift(iso: string, days: number): string {
  const [y = 0, m = 1, d = 1] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d) + days * DAY_MS).toISOString().slice(0, 10);
}

function addYears(iso: string, years: number): string {
  const [y = 0, m = 1, d = 1] = iso.split("-").map(Number);
  const moved = new Date(Date.UTC(y + years, m - 1, d));
  if (moved.getUTCMonth() !== m - 1) moved.setUTCDate(0); // 29 февраля -> 28 февраля
  return moved.toISOString().slice(0, 10);
}

function seed(): Stored[] {
  const today = companyToday();
  const now = new Date().toISOString();
  const common = {
    vakolat_url: null,
    note: null,
    createdById: "u-demo-admin",
    created_at: now,
    updated_at: now,
  };
  const issued = (byId: string): Stored["journal"] => [
    { at: now, action: "issued", byId, comment: null, changes: [], file_name: null },
  ];
  return [
    {
      ...common,
      id: "80000000-0000-4000-8000-000000000001",
      holderId: "u-demo-director",
      kinds: ALL_KINDS,
      limit: null,
      basis: "charter",
      basis_number: null,
      basis_date: null,
      valid_from: shift(today, -400),
      valid_to: null,
      file: null,
      revoked: null,
      journal: issued("u-demo-admin"),
    },
    {
      ...common,
      id: "80000000-0000-4000-8000-000000000002",
      holderId: "u-demo-manager",
      kinds: ["letter_out", "quote"],
      limit: { amount: "50000000.00", currency: "UZS" },
      basis: "power_of_attorney",
      basis_number: "17",
      basis_date: shift(today, -350),
      valid_from: shift(today, -350),
      valid_to: shift(today, 14),
      file: {
        name: "doverennost-17.pdf",
        content_type: "application/pdf",
        size: 183_000,
        version: 1,
        at: now,
      },
      revoked: null,
      journal: [
        ...issued("u-demo-admin"),
        {
          at: now,
          action: "file_replaced",
          byId: "u-demo-admin",
          comment: null,
          changes: [],
          file_name: "doverennost-17.pdf",
        },
        {
          at: now,
          action: "expiry_reminded",
          byId: null,
          comment: null,
          changes: [],
          file_name: null,
        },
      ],
    },
    {
      ...common,
      id: "80000000-0000-4000-8000-000000000003",
      holderId: "u-demo-accountant",
      kinds: ["invoice", "act"],
      limit: null,
      basis: "order",
      basis_number: "12-к",
      basis_date: shift(today, -120),
      valid_from: shift(today, -120),
      valid_to: null,
      file: null,
      revoked: null,
      journal: issued("u-demo-admin"),
    },
    {
      ...common,
      id: "80000000-0000-4000-8000-000000000004",
      holderId: "u-demo-supply",
      kinds: ["letter_out"],
      limit: { amount: "5000.00", currency: "USD" },
      basis: "power_of_attorney",
      basis_number: "9",
      basis_date: shift(today, -500),
      valid_from: shift(today, -500),
      valid_to: shift(today, -10),
      file: null,
      revoked: null,
      journal: issued("u-demo-admin"),
    },
    {
      ...common,
      id: "80000000-0000-4000-8000-000000000005",
      holderId: "u-demo-engineer",
      kinds: ["act"],
      limit: null,
      basis: "order",
      basis_number: "3-к",
      basis_date: shift(today, -200),
      valid_from: shift(today, -200),
      valid_to: null,
      file: null,
      revoked: { at: now, byId: "u-demo-admin", reason: "Сотрудник переведён в другой отдел" },
      journal: [
        ...issued("u-demo-admin"),
        {
          at: now,
          action: "revoked",
          byId: "u-demo-admin",
          comment: "Сотрудник переведён в другой отдел",
          changes: [],
          file_name: null,
        },
      ],
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
  memory ??= seed();
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

export function resetSigningMock(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}

export function readSigningAuthorities(): Stored[] {
  return read();
}

setSigningKindUsage(() => new Set(read().flatMap((item) => item.kinds)));

function who() {
  const session = readSession();
  if (!session) return null;
  const me = buildMe({ ...session, activeRole: null });
  const user = sessionRoles(session)?.user;
  if (!me || !user) return null;
  return { id: user.id, keeper: allows(me.resources, "eds.signing.manage", "full") };
}

const failure = (
  status: number,
  code: string,
  message: string,
  details?: Record<string, unknown>,
) =>
  HttpResponse.json(
    {
      code,
      message,
      source: status === 403 && !details ? "bff" : "eds",
      ...(details ? { details } : {}),
    },
    { status },
  );

const forbidden = () =>
  HttpResponse.json(
    {
      code: "FORBIDDEN",
      message: "Раздел или действие не положены вашей роли.",
      source: "bff",
      details: { resource: "eds.signing.manage", need: "full" },
    },
    { status: 403 },
  );

const expired = () => failure(401, "SESSION_EXPIRED", "Сессия истекла");

function person(id: string): PersonRef {
  return personOf(id) ?? { id, name: `Сотрудник ${id}`, initials: "СТ" };
}

function statusOf(item: Stored, today: string): SigningAuthorityStatus {
  if (item.revoked) return "revoked";
  if (today < item.valid_from) return "scheduled";
  if (item.valid_to !== null) {
    if (today > item.valid_to) return "expired";
    const left = Math.round((Date.parse(item.valid_to) - Date.parse(today)) / DAY_MS);
    if (left <= EXPIRING_DAYS) return "expiring";
  }
  return "active";
}

function holderPosition(id: string): string | null {
  const found = personOf(id);
  return found ? (DEMO_POSITIONS[id] ?? null) : null;
}

const DEMO_POSITIONS: Record<string, string> = {
  "u-demo-director": "Директор",
  "u-demo-manager": "Менеджер по продажам",
  "u-demo-accountant": "Бухгалтер",
  "u-demo-supply": "Специалист по снабжению",
  "u-demo-engineer": "Главный инженер",
};

function present(item: Stored): SigningAuthority {
  const today = companyToday();
  const left =
    item.valid_to === null || item.revoked || item.valid_to < today
      ? null
      : Math.round((Date.parse(item.valid_to) - Date.parse(today)) / DAY_MS);
  return {
    id: item.id,
    holder: person(item.holderId),
    holder_position: holderPosition(item.holderId),
    holder_active: true,
    kinds: item.kinds,
    limit: item.limit,
    basis: item.basis,
    basis_number: item.basis_number,
    basis_date: item.basis_date,
    valid_from: item.valid_from,
    valid_to: item.valid_to,
    vakolat_url: item.vakolat_url,
    note: item.note,
    file: item.file
      ? {
          name: item.file.name,
          content_type: item.file.content_type,
          size: item.file.size,
          version: item.file.version,
          uploaded_at: item.file.at,
        }
      : null,
    status: statusOf(item, today),
    expires_in_days: left,
    revoked: item.revoked
      ? { at: item.revoked.at, by: person(item.revoked.byId), reason: item.revoked.reason }
      : null,
    created_by: person(item.createdById),
    created_at: item.created_at,
    updated_at: item.updated_at,
  };
}

function detail(item: Stored): SigningAuthorityDetail {
  return {
    ...present(item),
    journal: item.journal.map((entry) => ({
      at: entry.at,
      action: entry.action,
      by: entry.byId ? person(entry.byId) : null,
      comment: entry.comment,
      changes: entry.changes,
      file_name: entry.file_name,
    })),
  };
}

type Terms = Pick<
  Stored,
  | "kinds"
  | "basis"
  | "basis_number"
  | "basis_date"
  | "valid_from"
  | "valid_to"
  | "limit"
  | "vakolat_url"
>;

/** Нарушения условий — поля для `details.fields` (как проверяет EDS). */
function problems(t: Terms): string[] {
  const bad: string[] = [];
  if (t.kinds.length === 0) bad.push("kinds");
  if (t.valid_to !== null && t.valid_to < t.valid_from) bad.push("valid_to");
  if (
    t.vakolat_url !== null &&
    !/^https:\/\/([a-z0-9-]+\.)*vakolat\.uz(\/|$)/i.test(t.vakolat_url)
  ) {
    bad.push("vakolat_url");
  }
  if (t.basis === "charter") {
    if (t.basis_number) bad.push("basis_number");
    return bad;
  }
  if (!t.basis_number) bad.push("basis_number");
  if (!t.basis_date) bad.push("basis_date");
  if (t.basis === "power_of_attorney") {
    if (t.valid_to === null) bad.push("valid_to");
    if (t.basis_date) {
      if (t.valid_from < t.basis_date) bad.push("valid_from");
      if (t.valid_to !== null && t.valid_to > addYears(t.basis_date, 3)) bad.push("valid_to");
    }
  }
  return [...new Set(bad)];
}

const invalid = (fields: string[]) =>
  failure(422, "VALIDATION_FAILED", "Проверьте полномочие.", { fields });

const blank = (value: string | null | undefined): string | null => {
  const text = (value ?? "").trim();
  return text === "" ? null : text;
};

function find(id: unknown): Stored | undefined {
  return read().find((item) => item.id === id);
}

function replace(next: Stored): void {
  write(read().map((item) => (item.id === next.id ? next : item)));
}

const FIELD_OF: Record<string, (t: Terms) => string | null> = {
  kinds: (t) => t.kinds.join(", "),
  limit_amount: (t) => t.limit?.amount ?? null,
  limit_currency: (t) => t.limit?.currency ?? null,
  basis: (t) => t.basis,
  basis_number: (t) => t.basis_number,
  basis_date: (t) => t.basis_date,
  valid_from: (t) => t.valid_from,
  valid_to: (t) => t.valid_to,
  vakolat_url: (t) => t.vakolat_url,
};

function applyPatch(current: Stored, patch: SigningAuthorityPatch): Stored {
  const next: Stored = { ...current };
  if (patch.kinds !== undefined) next.kinds = patch.kinds;
  if (patch.basis !== undefined) next.basis = patch.basis;
  if (patch.basis_number !== undefined) next.basis_number = blank(patch.basis_number);
  if (patch.basis_date !== undefined) next.basis_date = patch.basis_date;
  if (patch.valid_from !== undefined) next.valid_from = patch.valid_from;
  if (patch.valid_to !== undefined) next.valid_to = patch.valid_to;
  if (patch.vakolat_url !== undefined) next.vakolat_url = blank(patch.vakolat_url);
  if (patch.note !== undefined) next.note = blank(patch.note);
  if (patch.limit !== undefined) next.limit = patch.limit;
  return next;
}

const REASON_TEXT: Record<SigningRejected["reason"], string> = {
  revoked: "полномочие отозвано.",
  not_started: "полномочие ещё не началось.",
  expired: "срок полномочия вышел.",
  limit_exceeded: "сумма превышает лимит.",
  currency_mismatch: "лимит задан в другой валюте.",
  holder_inactive: "сотрудник отключён.",
  absent: "отсутствует, задача переходит заместителю.",
  deputy_without_authority: "замещение прав не даёт.",
  deputy_loop: "цепочка заместителей замкнулась.",
};

function resolve(
  kind: string,
  amount: string | null,
  currency: string | null,
  onDate: string,
): SigningResolution {
  const candidates: SignerCandidate[] = [];
  const rejected: SigningRejected[] = [];
  const steps: SigningResolution["explanation"] = [];
  const asked = amount !== null && currency !== null;
  for (const item of read().filter((entry) => entry.kinds.includes(kind))) {
    const holder = person(item.holderId);
    let reason: SigningRejected["reason"] | null = null;
    if (item.revoked) reason = "revoked";
    else if (onDate < item.valid_from) reason = "not_started";
    else if (item.valid_to !== null && onDate > item.valid_to) reason = "expired";
    else if (item.limit && asked) {
      if (item.limit.currency !== currency) reason = "currency_mismatch";
      else if (Number(amount) > Number(item.limit.amount)) reason = "limit_exceeded";
    }
    if (reason) {
      const message = `${holder.name}: ${REASON_TEXT[reason]}`;
      rejected.push({ signer: holder, authority_id: item.id, reason, message });
      steps.push({ code: reason, person_id: holder.id, text: message });
      continue;
    }
    const ref: SigningResolvedAuthority = {
      id: item.id,
      basis: item.basis,
      basis_number: item.basis_number,
      basis_date: item.basis_date,
      valid_to: item.valid_to,
      limit: item.limit,
    };
    candidates.push({
      signer: holder,
      position: holderPosition(item.holderId),
      acting_for: [],
      authority: ref,
      authorities: [ref],
      basis_text: null,
    });
    steps.push({
      code: "candidate",
      person_id: holder.id,
      text: `${holder.name} вправе подписать.`,
    });
  }
  if (candidates.length === 0) {
    steps.push({
      code: "no_signer",
      person_id: null,
      text: "Подписать некому — см. причины выше.",
    });
  }
  return {
    kind,
    amount: asked ? { amount, currency } : null,
    on_date: onDate,
    resolved: candidates.length > 0,
    candidates,
    rejected,
    explanation: steps,
  };
}

export const signingHandlers = [
  http.get("*/eds/signing/authorities", ({ request }) => {
    const me = who();
    if (!me) return expired();
    if (!me.keeper) return forbidden();
    const url = new URL(request.url);
    const wanted = url.searchParams.get("status") ?? "all";
    const holder = url.searchParams.get("holder_id");
    const groups: Record<string, readonly SigningAuthorityStatus[] | null> = {
      all: null,
      active: ["active", "expiring"],
      expiring: ["expiring"],
      inactive: ["scheduled", "expired", "revoked"],
    };
    const allowed = groups[wanted] ?? null;
    const items = read()
      .filter((item) => !holder || item.holderId === holder)
      .map(present)
      .filter((item) => !allowed || allowed.includes(item.status))
      .sort(
        (a, b) =>
          a.holder.name.localeCompare(b.holder.name, "ru") ||
          a.valid_from.localeCompare(b.valid_from),
      );
    return HttpResponse.json({ items });
  }),

  http.post("*/eds/signing/authorities", async ({ request }) => {
    const me = who();
    if (!me) return expired();
    if (!me.keeper) return forbidden();
    const body = (await request.json()) as SigningAuthorityIn;
    const terms: Terms = {
      kinds: body.kinds,
      basis: body.basis,
      basis_number: blank(body.basis_number),
      basis_date: body.basis_date ?? null,
      valid_from: body.valid_from,
      valid_to: body.valid_to ?? null,
      limit: body.limit ?? null,
      vakolat_url: blank(body.vakolat_url),
    };
    const bad = problems(terms);
    if (!personOf(body.holder_id)) bad.push("crm_user_id");
    if (bad.length > 0) return invalid(bad);
    const now = new Date().toISOString();
    const created: Stored = {
      ...terms,
      id: crypto.randomUUID(),
      holderId: body.holder_id,
      note: blank(body.note),
      file: null,
      revoked: null,
      createdById: me.id,
      created_at: now,
      updated_at: now,
      journal: [
        { at: now, action: "issued", byId: me.id, comment: null, changes: [], file_name: null },
      ],
    };
    write([...read(), created]);
    return HttpResponse.json(detail(created), { status: 201 });
  }),

  http.get("*/eds/signing/authorities/:id", ({ params }) => {
    const me = who();
    if (!me) return expired();
    if (!me.keeper) return forbidden();
    const item = find(params["id"]);
    return item
      ? HttpResponse.json(detail(item))
      : failure(404, "NOT_FOUND", "Полномочие не найдено.");
  }),

  http.patch("*/eds/signing/authorities/:id", async ({ params, request }) => {
    const me = who();
    if (!me) return expired();
    if (!me.keeper) return forbidden();
    const current = find(params["id"]);
    if (!current) return failure(404, "NOT_FOUND", "Полномочие не найдено.");
    if (current.revoked) {
      return failure(409, "CONFLICT", "Полномочие отозвано.", { reason: "revoked" });
    }
    const next = applyPatch(current, (await request.json()) as SigningAuthorityPatch);
    const bad = problems(next);
    if (bad.length > 0) return invalid(bad);
    const changes = Object.entries(FIELD_OF).flatMap(([field, get]) => {
      const before = get(current);
      const after = get(next);
      return before === after ? [] : [{ field, before, after }];
    });
    const now = new Date().toISOString();
    const saved: Stored =
      changes.length === 0
        ? next
        : {
            ...next,
            updated_at: now,
            journal: [
              ...next.journal,
              { at: now, action: "updated", byId: me.id, comment: null, changes, file_name: null },
            ],
          };
    replace(saved);
    return HttpResponse.json(detail(saved));
  }),

  http.post("*/eds/signing/authorities/:id/revoke", async ({ params, request }) => {
    const me = who();
    if (!me) return expired();
    if (!me.keeper) return forbidden();
    const current = find(params["id"]);
    if (!current) return failure(404, "NOT_FOUND", "Полномочие не найдено.");
    if (current.revoked) {
      return failure(409, "CONFLICT", "Полномочие отозвано.", { reason: "revoked" });
    }
    const { reason } = (await request.json()) as { reason: string };
    if (reason.trim().length < 3) return invalid(["reason"]);
    const now = new Date().toISOString();
    const saved: Stored = {
      ...current,
      revoked: { at: now, byId: me.id, reason: reason.trim() },
      updated_at: now,
      journal: [
        ...current.journal,
        {
          at: now,
          action: "revoked",
          byId: me.id,
          comment: reason.trim(),
          changes: [],
          file_name: null,
        },
      ],
    };
    replace(saved);
    return HttpResponse.json(detail(saved));
  }),

  http.post("*/eds/signing/authorities/:id/basis-file", async ({ params, request }) => {
    const me = who();
    if (!me) return expired();
    if (!me.keeper) return forbidden();
    const current = find(params["id"]);
    if (!current) return failure(404, "NOT_FOUND", "Полномочие не найдено.");
    if (current.revoked) {
      return failure(409, "CONFLICT", "Полномочие отозвано.", { reason: "revoked" });
    }
    const form = await request.formData();
    const file = form.get("file");
    if (!(file instanceof File)) return invalid(["file"]);
    if (!/^(application\/pdf|image\/)/.test(file.type)) {
      return failure(415, "UNSUPPORTED_MEDIA_TYPE", "Допустимы PDF и изображения.");
    }
    const now = new Date().toISOString();
    const saved: Stored = {
      ...current,
      file: {
        name: file.name,
        content_type: file.type,
        size: file.size,
        version: (current.file?.version ?? 0) + 1,
        at: now,
      },
      updated_at: now,
      journal: [
        ...current.journal,
        {
          at: now,
          action: "file_replaced",
          byId: me.id,
          comment: null,
          changes: [],
          file_name: file.name,
        },
      ],
    };
    replace(saved);
    return HttpResponse.json(detail(saved));
  }),

  http.get("*/eds/signing/authorities/:id/basis-file", ({ params }) => {
    const me = who();
    if (!me) return expired();
    if (!me.keeper) return forbidden();
    const item = find(params["id"]);
    if (!item?.file) return failure(404, "NOT_FOUND", "Файл основания не приложен.");
    return new HttpResponse("%PDF-1.4 demo", {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(item.file.name)}`,
      },
    });
  }),

  http.get("*/eds/signing/resolve", ({ request }) => {
    const me = who();
    if (!me) return expired();
    if (!me.keeper) return forbidden();
    const url = new URL(request.url);
    const kind = url.searchParams.get("kind") ?? "";
    const amount = url.searchParams.get("amount");
    const currency = url.searchParams.get("currency");
    if ((amount === null) !== (currency === null))
      return invalid(amount ? ["currency"] : ["amount"]);
    return HttpResponse.json(
      resolve(kind, amount, currency, url.searchParams.get("on_date") ?? companyToday()),
    );
  }),

  http.get("*/eds/signing/setup-hint", () => {
    const me = who();
    if (!me) return expired();
    if (!me.keeper) return forbidden();
    const director = personOf("u-demo-director") ?? null;
    return HttpResponse.json({
      has_authorities: read().length > 0,
      signatory_name: director?.name ?? null,
      signatory_position: "Директор",
      director,
    });
  }),
];
