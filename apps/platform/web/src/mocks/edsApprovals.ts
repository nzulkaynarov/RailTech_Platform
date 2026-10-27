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
  DIRECTOR_PERSON,
  MOCK_USER_CRM_ID,
  findMemo,
  findQuote,
  readMemos,
  readQuotes,
  writeMemos,
  writeQuotes,
} from "./fixtures/approvals";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки EDS · КП на одобрение и документы на согласовании (D1-4, BFF 0.22.0). Права — как в BFF: КП — `eds.drafts` (чтение —
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
  source: "bff" | "eds" = "bff",
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

/** Тому, кто не решает шаг КП, EDS снимок не отдаёт; а без `cost_margin` BFF вырезает экономику. */
function presentQuote(
  card: QuoteApprovalCard,
  margin: boolean,
  mayDecide: boolean,
): QuoteApprovalCard {
  const view: QuoteApprovalCard = {
    ...card,
    can_decide: card.can_decide && mayDecide,
    allowed_decisions: mayDecide ? card.allowed_decisions : [],
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

  http.get("*/eds/quotes/*", ({ request }) => {
    const ok = guard(QUOTES, "read");
    if (ok.error) return ok.error;
    const card = findQuote(refOf(request, "/eds/quotes/"));
    if (!card) return failure(404, "NOT_FOUND", "КП не найдено.", "eds", { backend_status: 404 });
    return HttpResponse.json(
      presentQuote(card, ok.who.margin, ok.who.levels["eds.drafts"] === "full"),
    );
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
      allowed_decisions: can ? ["approve", "return", "reject"] : [],
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
    return HttpResponse.json(next);
  }),
];
