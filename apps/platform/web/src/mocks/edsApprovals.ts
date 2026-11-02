import { HttpResponse, http } from "msw";

import type {
  ApprovalDecision,
  EdsPerson,
  ApprovalRouteStatus,
  EdsRouteStep,
  MemoApprovalCard,
  MemoApprovalPage,
  MemoApprovalRow,
  MemoDecisionIn,
  QuoteApprovalCard,
  QuoteApprovalPage,
  QuoteApprovalRow,
  QuoteDecisionIn,
} from "../shared/api/generated/model";
import {
  ACCOUNTANT_PERSON,
  AWAITING_CLIENT,
  DIRECTOR_PERSON,
  MANAGER_PERSON,
  deliveryAfterApproval,
  deliveryAfterSend,
  MOCK_USER_CRM_ID,
  findMemo,
  findQuote,
  readMemos,
  readQuotes,
  writeMemos,
  writeQuotes,
} from "./fixtures/approvals";
import { recordReturn } from "./fixtures/edsDocuments";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки EDS · КП на одобрение и документы на согласовании (D1-4, BFF 0.24.0). Права — как в BFF: КП — `eds.drafts` (чтение —
 * список и карточка, полный — решение), документы — `eds.memo.approve` (полный — решение) и чтение у `eds.memo.create`
 * (автор видит свои). Себестоимость и маржа без группы `cost_margin` не отдаются. Ошибки EDS — те же коды и подкоды
 * (`checklist_not_green`, `route_closed`), чтобы экран и e2e видели настоящее поведение.
 */
type Level = "read" | "full";
type Held = Partial<Record<string, Level>>;

function failure(
  status: number,
  code: string,
  message: string,
  source: "bff" | "eds" | "erp" = "bff",
  details?: Record<string, unknown>,
) {
  return HttpResponse.json({ code, message, source, ...(details ? { details } : {}) }, { status });
}

function held(): { levels: Held; margin: boolean; crmId: number | undefined } | null {
  const session = readSession();
  if (!session) return null;
  // Права операций — по объединению ролей, а не по активной роли («вид»), как в BFF.
  const me = buildMe({ ...session, activeRole: null });
  if (!me) return null;
  return {
    levels: me.resources,
    margin: (me.restricted_fields ?? []).includes("cost_margin"),
    crmId: MOCK_USER_CRM_ID[session.userId],
  };
}

function guard(resources: readonly string[], need: Level) {
  const who = held();
  if (!who) return { error: failure(401, "SESSION_EXPIRED", "Сессия истекла") };
  const ok = resources.some((r) => {
    const level = who.levels[r];
    return level === "full" || (need === "read" && level === "read");
  });
  if (!ok) {
    return {
      error: failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
        resource: resources[0],
        need,
      }),
    };
  }
  return { who };
}

const QUOTES = ["eds.drafts"] as const;
const MEMO_READ = ["eds.memo.approve", "eds.memo.create"] as const;
// Решает директор (`eds.memo.approve`) или бухгалтер на своём шаге (`eds.payments` — полный).
const MEMO_DECIDE = ["eds.memo.approve", "eds.payments"] as const;

function mayDecideAny(levels: Held): boolean {
  return levels["eds.memo.approve"] === "full" || levels["eds.payments"] === "full";
}

/** Чей сейчас шаг, знает EDS: шаг «Бухгалтер» решают держатели `eds.payments`, остальные — `eds.memo.approve`. */
function canDecideMemo(card: MemoApprovalCard, levels: Held): boolean {
  const current = card.steps.find((s) => s.status === "current");
  if (card.status !== "open" || !current) return false;
  const resource = current.label === "Бухгалтер" ? "eds.payments" : "eds.memo.approve";
  return levels[resource] === "full";
}

function refOf(request: Request, prefix: string): string {
  const path = new URL(request.url).pathname;
  const tail = path.slice(path.indexOf(prefix) + prefix.length);
  try {
    return decodeURIComponent(tail);
  } catch {
    return tail;
  }
}

function paged<T>(url: URL, all: T[]): { items: T[]; next_cursor: string | null } {
  const limit = Number(url.searchParams.get("limit") ?? 50);
  const start = Number(url.searchParams.get("cursor") ?? 0);
  return {
    items: all.slice(start, start + limit),
    next_cursor: start + limit < all.length ? String(start + limit) : null,
  };
}

function wantedStatuses(url: URL): ApprovalRouteStatus[] {
  return url.searchParams.getAll("status") as ApprovalRouteStatus[];
}

// --- КП ------------------------------------------------------------------------------------------

/**
 * Поля и файл формы multipart без `request.formData()`: в jsdom (vitest) разбор форм в Node не знает чужой `File`
 * (как `scanVerdict` в моке проектов); мок работает и там, и в браузере.
 */
async function multipart(
  request: Request,
): Promise<{ fields: Record<string, string>; file: { name: string; size: number } | null }> {
  const boundary = /boundary=([^;]+)/.exec(request.headers.get("content-type") ?? "")?.[1];
  const fields: Record<string, string> = {};
  let file: { name: string; size: number } | null = null;
  if (!boundary) return { fields, file };
  const text = new TextDecoder().decode(await request.arrayBuffer());
  for (const part of text.split(`--${boundary}`)) {
    const split = part.indexOf("\r\n\r\n");
    if (split < 0) continue;
    const head = part.slice(0, split);
    const name = /name="([^"]*)"/.exec(head)?.[1];
    if (!name) continue;
    const body = part.slice(split + 4).replace(/\r\n$/, "");
    const filename = /filename="([^"]*)"/.exec(head)?.[1];
    if (filename !== undefined) file = { name: filename, size: body.length };
    else fields[name] = body;
  }
  return { fields, file };
}

/** Тому, кто не решает шаг КП, EDS снимок не отдаёт; а без `cost_margin` BFF вырезает экономику. */
function presentQuote(
  card: QuoteApprovalCard,
  margin: boolean,
  mayDecide: boolean,
  maySend = mayDecide,
): QuoteApprovalCard {
  const view: QuoteApprovalCard = {
    ...card,
    // «Отправить» — у того, кто отправляет КП (раздел «Клиенты» полный, ERP `quote.send`; D17G-2)
    delivery: card.delivery
      ? {
          ...card.delivery,
          lines: card.delivery.lines.map((l) => ({ ...l, can_send: l.can_send && maySend })),
        }
      : null,
    can_decide: card.can_decide && mayDecide,
    allowed_decisions: mayDecide ? card.allowed_decisions : [],
    // «Клиент принял / отклонил» — у того, кто ведёт клиента (раздел «Клиенты» полный, ERP `deal.manage`; A1)
    client_decision: card.client_decision
      ? { ...card.client_decision, can_record: card.client_decision.can_record && maySend }
      : null,
    // ERP отказывает роли без доступа к КП (403): состав и итоги не приходят, снимка EDS у неё нет
    ...(mayDecide
      ? {}
      : { lines: null, totals: null, snapshot_total: null, totals_mismatch: false }),
    checklist: card.checklist.map((c) => {
      if (c.code !== "margin" || margin) return c;
      return { code: c.code, ok: c.ok, blocking: c.blocking, by_name: c.by_name, at: c.at };
    }),
  };
  if (!margin) delete view.internal;
  return view;
}

function quoteRow(card: QuoteApprovalCard, mayDecide: boolean): QuoteApprovalRow {
  return {
    id: card.id,
    number: card.number,
    version: card.version,
    superseded_by: card.superseded_by,
    request_number: card.request?.number ?? null,
    client_name: mayDecide ? card.client_name : null,
    total:
      mayDecide && card.totals
        ? { amount: card.totals.total, currency: card.totals.currency }
        : null,
    due: mayDecide ? card.due : null,
    status: card.status,
    can_decide: card.can_decide && mayDecide,
    outgoing_number: card.outgoing_number,
    created_at: card.created_at,
  };
}

function updateQuote(id: string, change: (q: QuoteApprovalCard) => QuoteApprovalCard) {
  const all = readQuotes();
  const index = all.findIndex((q) => q.id === id);
  const current = all[index];
  if (index < 0 || !current) return undefined;
  const next = change(current);
  writeQuotes(all.map((q, i) => (i === index ? next : q)));
  return next;
}

const closedConflict = () =>
  failure(409, "CONFLICT", "Маршрут уже закрыт.", "eds", {
    backend_status: 409,
    reason: "route_closed",
  });

const STATUS_OF: Record<ApprovalDecision, ApprovalRouteStatus> = {
  approve: "approved",
  return: "returned",
  reject: "rejected",
};

const STEP_OF: Record<ApprovalDecision, EdsRouteStep["status"]> = {
  approve: "approved",
  return: "returned",
  reject: "rejected",
};

function decideSteps(
  steps: readonly EdsRouteStep[],
  decision: ApprovalDecision,
  comment: string | null | undefined,
  actor: EdsPerson = DIRECTOR_PERSON,
): EdsRouteStep[] {
  const now = new Date().toISOString();
  return steps.map((s, index) => {
    if (s.status === "current") {
      return {
        ...s,
        status: STEP_OF[decision],
        decided_by: actor,
        decided_at: now,
        comment: comment ?? null,
      };
    }
    if (s.status !== "pending") return s;
    // «Согласовано» директором с суммой передаёт шаг бухгалтеру; возврат и отказ закрывают остальные шаги
    const handedOver = steps[index - 1]?.status === "current" && decision === "approve";
    return { ...s, status: handedOver ? "current" : "skipped" };
  });
}

export const edsApprovalsHandlers = [
  http.get("*/eds/quotes", ({ request }) => {
    const ok = guard(QUOTES, "read");
    if (ok.error) return ok.error;
    const url = new URL(request.url);
    const mine = (url.searchParams.get("scope") ?? "mine") === "mine";
    const mayDecide = ok.who.levels["eds.drafts"] === "full";
    const statuses = wantedStatuses(url);
    const found = readQuotes()
      .filter((q) => (mine ? q.status === "open" && q.can_decide && mayDecide : true))
      .filter((q) => statuses.length === 0 || statuses.includes(q.status))
      .map((q) => quoteRow(q, mayDecide));
    const page: QuoteApprovalPage = paged(url, found);
    return HttpResponse.json(page);
  }),

  // A1: файл подтверждения клиента — раньше карточки по номеру (`/eds/quotes/*` съел бы адрес).
  http.get("*/eds/quotes/:id/client-decision/evidence", ({ params }) => {
    const ok = guard(QUOTES, "read");
    if (ok.error) return ok.error;
    const card = findQuote(String(params["id"]));
    if (!card?.client_decision?.recorded_by_staff?.evidence_url) {
      return failure(404, "NOT_FOUND", "Файла подтверждения нет.", "bff");
    }
    return new HttpResponse(new Blob(["%PDF-1.4 demo"]), {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": 'attachment; filename="client-confirmation.pdf"',
      },
    });
  }),

  http.get("*/eds/quotes/*", ({ request }) => {
    const ok = guard(QUOTES, "read");
    if (ok.error) return ok.error;
    const card = findQuote(refOf(request, "/eds/quotes/"));
    if (!card) return failure(404, "NOT_FOUND", "КП не найдено.", "eds", { backend_status: 404 });
    return HttpResponse.json(
      presentQuote(
        card,
        ok.who.margin,
        ok.who.levels["eds.drafts"] === "full",
        ok.who.levels["crm.clients"] === "full",
      ),
    );
  }),

  http.post("*/eds/quotes/:id/send", async ({ request, params }) => {
    const ok = guard(["crm.clients"], "full");
    if (ok.error) return ok.error;
    const card = findQuote(String(params["id"]));
    if (!card) return failure(404, "NOT_FOUND", "КП не найдено.", "eds");
    const { channel } = (await request.json()) as { channel: string };
    if (channel !== "telegram" && channel !== "email") {
      return failure(422, "VALIDATION_FAILED", "Канал не отправляется.", "bff", {
        fields: ["channel"],
      });
    }
    if (!card.delivery || card.delivery.state === "closed") {
      return failure(409, "CONFLICT", "КП не отправлено.", "erp", { reason: "invalid_status" });
    }
    if (card.channels && !card.channels[channel]) {
      return failure(409, "CONFLICT", "КП не отправлено.", "erp", {
        reason: card.channels.reasons[channel] ?? "send_failed",
      });
    }
    const delivery = card.delivery;
    const next = updateQuote(card.id, (current) => ({
      ...current,
      delivery: deliveryAfterSend(delivery, channel),
    }));
    return HttpResponse.json(presentQuote(next ?? card, ok.who.margin, false, true));
  }),

  http.post("*/eds/quotes/:id/client-decision", async ({ request, params }) => {
    const ok = guard(["crm.clients"], "full");
    if (ok.error) return ok.error;
    const card = findQuote(String(params["id"]));
    if (!card) return failure(404, "NOT_FOUND", "КП не найдено.", "eds");
    const form = await multipart(request);
    const text = (name: string) => (form.fields[name] ?? "").trim();
    const file = form.file;
    const invalid = (field: string, reason: string, message: string) =>
      failure(422, "VALIDATION_FAILED", message, "erp", { fields: [field], reason });
    if (!file || file.size === 0) {
      return invalid(
        "file",
        "evidence_required",
        "Приложите подтверждение клиента: письмо, переписку или скан.",
      );
    }
    if (!text("counterparty_person")) {
      return invalid(
        "counterparty_person",
        "counterparty_person_required",
        "Укажите, кто со стороны клиента.",
      );
    }
    if (!text("comment")) return invalid("comment", "comment_required", "Заполните комментарий.");
    if (card.client_decision?.state !== "awaiting") {
      return failure(409, "CONFLICT", "КП уже не ждёт решения клиента. Обновите страницу.", "erp", {
        backend_status: 409,
        reason: "quote_not_sent",
      });
    }
    const accept = text("decision") === "accept";
    const decidedAt = new Date().toISOString();
    const next = updateQuote(card.id, (current) => ({
      ...current,
      stage: accept ? "CONTRACT" : "CALCULATION",
      delivery: current.delivery
        ? {
            ...current.delivery,
            state: "closed",
            lines: current.delivery.lines.map((line) => ({ ...line, can_send: false })),
          }
        : null,
      client_decision: {
        state: accept ? "accepted" : "rejected",
        decided_at: decidedAt,
        reason: accept ? null : text("comment"),
        can_record: false,
        recorded_by_staff: {
          staff_name: MANAGER_PERSON.full_name,
          channel: text("channel") as NonNullable<
            NonNullable<QuoteApprovalCard["client_decision"]>["recorded_by_staff"]
          >["channel"],
          counterparty_person: text("counterparty_person"),
          occurred_on: text("occurred_on") || null,
          comment: text("comment"),
          evidence_name: file.name,
          evidence_url: `/api/v1/eds/quotes/${current.id}/client-decision/evidence`,
        },
      },
    }));
    return HttpResponse.json(presentQuote(next ?? card, ok.who.margin, false, true));
  }),

  http.post("*/eds/quotes/:id/decision", async ({ request, params }) => {
    const ok = guard(QUOTES, "full");
    if (ok.error) return ok.error;
    const card = findQuote(String(params["id"]));
    if (!card) return failure(404, "NOT_FOUND", "КП не найдено.", "eds");
    const body = (await request.json()) as QuoteDecisionIn;
    if ((body.decision === "return" || body.decision === "reject") && !body.comment?.trim()) {
      return failure(422, "VALIDATION_FAILED", "Комментарий обязателен.", "bff", {
        fields: ["comment"],
      });
    }
    if (card.status !== "open") return closedConflict();
    if (!card.allowed_decisions.includes(body.decision)) {
      const failed = card.checklist.filter((c) => c.blocking && !c.ok).map((c) => c.code);
      return failure(409, "CONFLICT", "Чек-лист одобрения не выполнен.", "eds", {
        backend_status: 409,
        reason: "checklist_not_green",
        failed,
      });
    }
    const late =
      body.decision === "approve" && card.checklist.some((c) => c.code === "due" && !c.ok);
    const next = updateQuote(card.id, (current) => ({
      ...current,
      status: STATUS_OF[body.decision],
      can_decide: false,
      allowed_decisions: [],
      approved_late: late,
      outgoing_number:
        body.decision === "approve" ? `ИСХ-0${String(40 + current.version)}/26` : null,
      // ERP-11: одобрение с каналами сразу отправляет КП по доступным из них (отчёт — D17G-2)
      delivery:
        body.decision === "approve"
          ? deliveryAfterApproval(current.channels, body.channels ?? [])
          : null,
      // Отправленное КП ждёт решения клиента (A1)
      client_decision:
        body.decision === "approve" && (body.channels ?? []).length > 0 ? AWAITING_CLIENT : null,
      steps: decideSteps(current.steps, body.decision, body.comment),
    }));
    return HttpResponse.json(
      next ? presentQuote(next, ok.who.margin, true) : presentQuote(card, ok.who.margin, true),
    );
  }),

  // --- документы на согласовании ---------------------------------------------------------------

  http.get("*/eds/memo-approvals", ({ request }) => {
    const ok = guard(MEMO_READ, "read");
    if (ok.error) return ok.error;
    const url = new URL(request.url);
    const mine = (url.searchParams.get("scope") ?? "mine") === "mine";
    const mayDecide = mayDecideAny(ok.who.levels);
    const statuses = wantedStatuses(url);
    const found = readMemos()
      .filter((m) =>
        mine ? canDecideMemo(m, ok.who.levels) : mayDecide || m.author.crm_user_id === ok.who.crmId,
      )
      .filter((m) => statuses.length === 0 || statuses.includes(m.status))
      .map((m): MemoApprovalRow => {
        const current = m.steps.find((s) => s.status === "current");
        return {
          id: m.id,
          approval_id: m.approval_id,
          number: m.number,
          kind: m.kind,
          subject: m.subject,
          author: m.author,
          amount: m.amount,
          due_date: m.due_date,
          status: m.status,
          step_label: current?.label ?? null,
          can_decide: canDecideMemo(m, ok.who.levels),
          created_at: m.created_at,
        };
      });
    const page: MemoApprovalPage = paged(url, found);
    return HttpResponse.json(page);
  }),

  http.get("*/eds/memo-approvals/*", ({ request }) => {
    const ok = guard(MEMO_READ, "read");
    if (ok.error) return ok.error;
    const card = findMemo(refOf(request, "/eds/memo-approvals/"));
    if (!card)
      return failure(404, "NOT_FOUND", "Документ не найден.", "eds", { backend_status: 404 });
    const can = canDecideMemo(card, ok.who.levels);
    const view: MemoApprovalCard = {
      ...card,
      can_decide: can,
      // EDS 0.5.0+ (B-D24-5): на шаге бухгалтера решения «Принять» нет — шаг закрывает «Оплачено» в «Счета и оплаты»
      allowed_decisions: can
        ? card.accountant_step
          ? ["return", "reject"]
          : ["approve", "return", "reject"]
        : [],
    };
    return HttpResponse.json(view);
  }),

  http.post("*/eds/memo-approvals/:id/decision", async ({ request, params }) => {
    const ok = guard(MEMO_DECIDE, "full");
    if (ok.error) return ok.error;
    const card = readMemos().find((m) => m.approval_id === String(params["id"]));
    if (!card) return failure(404, "NOT_FOUND", "Документ не найден.", "eds");
    const body = (await request.json()) as MemoDecisionIn;
    if ((body.decision === "return" || body.decision === "reject") && !body.comment?.trim()) {
      return failure(422, "VALIDATION_FAILED", "Комментарий обязателен.", "bff", {
        fields: ["comment"],
      });
    }
    if (card.status !== "open") return closedConflict();
    // Чей шаг, решает EDS: директор — шаг «Директор», бухгалтер — шаг «Бухгалтер»
    if (!canDecideMemo(card, ok.who.levels)) {
      return failure(403, "FORBIDDEN", "Сейчас не ваш шаг.", "eds", {
        backend_status: 403,
        reason: "not_your_step",
      });
    }
    const accountant = card.accountant_step;
    if (accountant && body.decision === "approve") {
      // EDS 0.5.0+: шаг бухгалтера закрывает «Оплачено» (`POST /documents/{id}/payment`), не решение «Принять»
      return failure(409, "CONFLICT", "Шаг бухгалтера закрывает «Оплачено».", "eds", {
        backend_status: 409,
        reason: "payment_required",
      });
    }
    const actor = accountant ? ACCOUNTANT_PERSON : DIRECTOR_PERSON;
    const goesOn = body.decision === "approve" && card.steps.some((s) => s.status === "pending");
    const steps = decideSteps(card.steps, body.decision, body.comment, actor);
    const next: MemoApprovalCard = {
      ...card,
      // Служебка с суммой после директора идёт бухгалтеру — маршрут остаётся открытым
      status: goesOn ? "open" : STATUS_OF[body.decision],
      document_status: goesOn
        ? "to_accountant"
        : accountant && body.decision === "approve"
          ? "to_accountant"
          : body.decision === "approve"
            ? "approved"
            : body.decision === "return"
              ? "returned"
              : "rejected",
      can_decide: false,
      allowed_decisions: [],
      accountant_step: goesOn,
      steps,
      decisions: [
        ...card.decisions,
        {
          round: card.round,
          step: steps.findIndex((s) => s.decided_at !== null && s.status !== "skipped") + 1 || 1,
          decision: body.decision,
          comment: body.comment ?? null,
          by: actor,
          at: new Date().toISOString(),
        },
      ],
    };
    writeMemos(readMemos().map((m) => (m.id === card.id ? next : m)));
    // Возврат — работа автора: документ становится «Возвращён на доработку» в его документах (строка «Доработать» в очереди).
    const last = next.decisions[next.decisions.length - 1];
    if (body.decision === "return" && last) recordReturn(next, last);
    return HttpResponse.json(next);
  }),
];
