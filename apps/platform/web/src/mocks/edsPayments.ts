import { HttpResponse, http } from "msw";

import type {
  EdsFile,
  MemoApprovalCard,
  PaymentBoard,
  PaymentCard,
  PaymentConfirmIn,
  PaymentMemoCard,
  PaymentMemoJournal,
  PaymentMemoPage,
  PaymentMemoPayIn,
  PaymentMemoRow,
  PaymentMemoStatus,
} from "../shared/api/generated/model";
import { ACCOUNTANT_PERSON, MOCK_USER_CRM_ID, readMemos, writeMemos } from "./fixtures/approvals";
import {
  ACCOUNTANT_NAME,
  TODAY,
  type Tab,
  counts,
  dec,
  findInvoice,
  fromCents,
  idempotent,
  memoPayments,
  newProofId,
  newReceiptId,
  readInvoices,
  receiptFiles,
  rowOf,
  statusOf,
  tabOf,
  writeInvoices,
} from "./fixtures/payments";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки EDS · Счета и оплаты бухгалтера (D2-4, BFF 0.26.0). Права — как в BFF: чтение — `eds.payments` (менеджер, директор,
 * бухгалтер), действия — полный. Каталог даёт чтению право ERP `finance.view` (Q-D2-4-1 п. 2), поэтому роль с чтением видит доску
 * и карточку; действия ей отказывает уже BFF (403 `bff`, `need = full`). Ошибки ERP и EDS — те же коды и подкоды, что в BFF
 * (`exceeds_balance`, `already_paid`, `exceeds_approved`), повтор подтверждения идемпотентен.
 */
type Level = "read" | "full";

function failure(
  status: number,
  code: string,
  message: string,
  source: "bff" | "erp" | "eds" = "bff",
  details?: Record<string, unknown>,
) {
  return HttpResponse.json({ code, message, source, ...(details ? { details } : {}) }, { status });
}

function held() {
  const session = readSession();
  if (!session) return null;
  const me = buildMe({ ...session, activeRole: null });
  if (!me) return null;
  return { level: me.resources["eds.payments"], crmId: MOCK_USER_CRM_ID[session.userId] };
}

function guard(need: Level) {
  const who = held();
  if (!who) return { error: failure(401, "SESSION_EXPIRED", "Сессия истекла") };
  const ok = who.level === "full" || (need === "read" && who.level === "read");
  if (!ok) {
    return {
      error: failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
        resource: "eds.payments",
        need,
      }),
    };
  }
  return { who };
}

const notFound = (message: string, source: "erp" | "eds" = "erp") =>
  failure(404, "NOT_FOUND", message, source, { backend_status: 404 });

function validationBff(...fields: string[]) {
  return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "bff", {
    fields: fields.map((f) => `body.${f}`),
  });
}

function update(id: number, change: (card: PaymentCard) => PaymentCard): PaymentCard | undefined {
  const all = readInvoices();
  const found = all.find((c) => c.id === id);
  if (!found) return undefined;
  const next = change(found);
  writeInvoices(all.map((c) => (c.id === id ? next : c)));
  return next;
}

/** Как в ERP: действия карточки — только с `finance.payment` (полный доступ к разделу); чтение — `finance.view`. */
function withFlags(card: PaymentCard): PaymentCard {
  const open =
    card.status !== "draft" &&
    card.status !== "paid" &&
    card.status !== "cancelled" &&
    held()?.level === "full";
  return { ...card, can_confirm: open, can_attach_proof: open, can_request_proof: open };
}

const money = (amount: string, currency: string) => ({ amount, currency });

function paged<T>(url: URL, all: T[], total?: number): { items: T[]; next_cursor: string | null } {
  const limit = Number(url.searchParams.get("limit") ?? 50);
  const start = Number(url.searchParams.get("cursor") ?? 0);
  return {
    items: all.slice(start, start + limit),
    next_cursor: start + limit < (total ?? all.length) ? String(start + limit) : null,
  };
}

// --- служебки к оплате: общий склад с «На согласовании» ----------------------------------------------

const MEMO_STATUS = (m: MemoApprovalCard): PaymentMemoStatus | "other" =>
  m.document_status === "to_accountant"
    ? "to_pay"
    : m.document_status === "paid"
      ? "paid"
      : "other";

const isPayable = (m: MemoApprovalCard) =>
  m.kind === "memo" && m.amount !== null && MEMO_STATUS(m) !== "other";

function memoRow(m: MemoApprovalCard): PaymentMemoRow {
  const payment = memoPayments.get(m.id);
  return {
    id: m.id,
    number: m.number,
    subject: m.subject,
    author: m.author,
    amount: m.amount,
    due_date: m.due_date,
    files_count: m.files.length,
    invoice_attached: m.files.length > 0,
    status: MEMO_STATUS(m) === "paid" ? "paid" : "to_pay",
    paid_on: payment?.paid_on ?? null,
    created_at: m.created_at,
  };
}

function memoJournal(m: MemoApprovalCard): PaymentMemoJournal[] {
  const entries: PaymentMemoJournal[] = [
    { at: m.created_at, action: "document.submitted", by: m.author, comment: null },
    ...m.decisions.map((d) => ({
      at: d.at,
      action: "approval.decided",
      by: d.by,
      comment: d.comment,
    })),
  ];
  const payment = memoPayments.get(m.id);
  if (payment) {
    entries.push({
      at: payment.recorded_at,
      action: "document.paid",
      by: payment.paid_by,
      comment: `${payment.paid_on}, ${payment.amount.amount} ${payment.amount.currency}`,
    });
  }
  return entries;
}

function memoCard(
  m: MemoApprovalCard,
  who: { level: Level | undefined; crmId: number | undefined },
): PaymentMemoCard {
  const status = MEMO_STATUS(m);
  const mine = who.crmId !== undefined && m.author.crm_user_id === who.crmId;
  const can = who.level === "full" && status === "to_pay" && m.accountant_step && !mine;
  return {
    id: m.id,
    approval_id: m.approval_id,
    number: m.number,
    subject: m.subject,
    text: m.text,
    author: m.author,
    amount: m.amount,
    due_date: m.due_date,
    deal: m.deal,
    files: m.files,
    document_status: m.document_status,
    status,
    can_pay: can,
    can_return: can,
    payment: memoPayments.get(m.id) ?? null,
    journal: memoJournal(m),
    created_at: m.created_at,
  };
}

/**
 * Файл из multipart без `request.formData()`: в jsdom (vitest) разбор форм в Node не знает чужой `File`, а мок работает и там,
 * и в браузере. Размер — по числу байт содержимого части.
 */
async function uploadedFile(
  request: Request,
): Promise<{ name: string; size: number; type: string } | null> {
  const boundary = /boundary=([^;]+)/.exec(request.headers.get("content-type") ?? "")?.[1];
  if (!boundary) return null;
  const text = new TextDecoder().decode(await request.arrayBuffer());
  for (const part of text.split(`--${boundary}`)) {
    const split = part.indexOf("\r\n\r\n");
    if (split < 0) continue;
    const head = part.slice(0, split);
    const name = /filename="([^"]*)"/.exec(head)?.[1];
    if (name === undefined || !/name="file"/.test(head)) continue;
    const body = part.slice(split + 4).replace(/\r\n$/, "");
    return {
      name,
      size: new TextEncoder().encode(body).length,
      type: /Content-Type:\s*([^\r\n]+)/i.exec(head)?.[1] ?? "",
    };
  }
  return null;
}

const EXT_BAD = /\.(exe|bat|cmd|js|sh)$/i;

export const edsPaymentsHandlers = [
  // Файлы вложений служебок к оплате (счёт поставщика, платёжка): демонстрационное содержимое
  http.get("*/eds/document-files/:id", ({ params }) => {
    const id = String(params["id"]);
    const receipt = receiptFiles.get(id);
    const memoFile = readMemos()
      .flatMap((m) => m.files)
      .find((f) => f.id === id);
    const file = receipt ?? memoFile;
    if (!file) return undefined;
    return new HttpResponse(`Демонстрационное содержимое файла «${file.name}».`, {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(file.name)}`,
      },
    });
  }),

  http.get("*/eds/payments", ({ request }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const url = new URL(request.url);
    const tab = (url.searchParams.get("tab") ?? "awaiting") as Tab;
    const needle = (url.searchParams.get("q") ?? "").trim().toLowerCase();
    const limit = Number(url.searchParams.get("limit") ?? 50);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const found = readInvoices()
      .filter((c) => tab === "all" || tabOf(c) === tab)
      .filter(
        (c) =>
          !needle ||
          c.number.toLowerCase().includes(needle) ||
          c.client_name.toLowerCase().includes(needle),
      )
      .sort((a, b) => (a.due_date ?? "9").localeCompare(b.due_date ?? "9") || a.id - b.id)
      .map(rowOf);
    const board: PaymentBoard = {
      tab,
      count: found.length,
      counts: counts(),
      memos_to_pay: readMemos().filter((m) => isPayable(m) && MEMO_STATUS(m) === "to_pay").length,
      items: found.slice(offset, offset + limit),
      sources: { erp: "ok", eds: "ok" },
    };
    return HttpResponse.json(board);
  }),

  http.get("*/eds/payments/:id", ({ params }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const card = findInvoice(Number(params["id"]));
    if (!card) return notFound("Счёт не найден.");
    return HttpResponse.json(withFlags(card));
  }),

  http.post("*/eds/payments/:id/confirm", async ({ request, params }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const key = request.headers.get("idempotency-key");
    if (key && idempotent.has(key)) return HttpResponse.json(idempotent.get(key));
    const body = (await request.json()) as PaymentConfirmIn;
    const cents = dec(body.amount);
    if (!(cents > 0) || !/^\d{1,12}\.\d{2}$/.test(body.amount)) {
      return validationBff("amount");
    }
    if (!body.date || body.date > TODAY) return validationBff("date");
    const card = findInvoice(Number(params["id"]));
    if (!card) return notFound("Счёт не найден.");
    const proof = body.proof_id ? card.proofs.find((p) => p.id === body.proof_id) : undefined;
    if (body.proof_id && !proof) return notFound("Платёжка не найдена.");
    if (proof?.status === "CONFIRMED") {
      return HttpResponse.json({ ...withFlags(card), replayed: true });
    }
    const last = card.payments[card.payments.length - 1];
    if (card.status === "paid") {
      if (last && dec(last.amount) === cents && last.paid_at === body.date) {
        return HttpResponse.json({ ...withFlags(card), replayed: true });
      }
      return failure(409, "CONFLICT", "Счёт уже оплачен полностью.", "erp", {
        backend_status: 409,
        reason: "already_paid",
      });
    }
    if (card.status === "draft") {
      return failure(409, "CONFLICT", "Счёт ещё не выставлен.", "erp", {
        backend_status: 409,
        reason: "not_issued",
      });
    }
    const balance = dec(card.balance.amount);
    if (cents > balance) {
      return failure(409, "CONFLICT", "Сумма больше остатка по счёту.", "erp", {
        backend_status: 409,
        reason: "exceeds_balance",
        fields: ["amount"],
      });
    }
    const now = new Date().toISOString();
    const currency = card.amount.currency;
    const paid = dec(card.paid.amount) + cents;
    const paymentId = card.id * 10 + card.payments.length + 1;
    const next = update(card.id, (current) => {
      const proofs = current.proofs.map((p) =>
        p.id === body.proof_id ? { ...p, status: "CONFIRMED" as const, payment_id: paymentId } : p,
      );
      const base: PaymentCard = {
        ...current,
        paid: money(fromCents(paid), currency),
        balance: money(fromCents(dec(current.amount.amount) - paid), currency),
        proofs,
        payments: [
          ...current.payments,
          {
            id: paymentId,
            amount: fromCents(cents),
            paid_at: body.date,
            method: "BANK_TRANSFER",
            reference: body.reference ?? "",
            receipt_number: `RCP-${String(paymentId)}`,
            has_proof: proof !== undefined,
            recorded_by: ACCOUNTANT_NAME,
            created_at: now,
          },
        ],
        history: [
          { at: now, code: "payment.recorded", text: "Зафиксирован платёж", by: ACCOUNTANT_NAME },
          ...current.history,
        ],
        replayed: false,
      };
      const cleaned: PaymentCard = {
        ...base,
        has_pending_proof: proofs.some((p) => p.status === "PENDING"),
        proof_received_at: proofs.find((p) => p.status === "PENDING")?.received_at ?? null,
      };
      const status = statusOf(
        {
          amount: cleaned.amount,
          paid: cleaned.paid,
          due_date: cleaned.due_date,
          issued_at: cleaned.issued_at,
          proofs,
        },
        false,
      );
      return withFlags({
        ...cleaned,
        status,
        days_overdue: status === "overdue" ? current.days_overdue : null,
      });
    });
    if (!next) return notFound("Счёт не найден.");
    if (key) idempotent.set(key, next);
    return HttpResponse.json(next);
  }),

  http.post("*/eds/payments/:id/proofs", async ({ request, params }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const card = findInvoice(Number(params["id"]));
    if (!card) return notFound("Счёт не найден.");
    if (card.status === "paid" || card.status === "draft" || card.status === "cancelled") {
      return failure(409, "CONFLICT", "Счёт не ждёт оплаты.", "erp", {
        backend_status: 409,
        reason: "not_open",
      });
    }
    const file = await uploadedFile(request);
    if (!file) {
      return failure(422, "VALIDATION_FAILED", "Файл нужно передать формой multipart.", "bff", {
        fields: ["file"],
        reason: "multipart_required",
      });
    }
    if (EXT_BAD.test(file.name)) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "erp", {
        backend_status: 400,
        fields: ["file"],
      });
    }
    const now = new Date().toISOString();
    const next = update(card.id, (current) => {
      const proofs = [
        ...current.proofs,
        {
          id: newProofId(),
          source: "EMAIL" as const,
          status: "PENDING" as const,
          original_name: file.name,
          claimed_amount: null,
          claimed_date: null,
          note: "",
          received_at: now,
          recorded_by: ACCOUNTANT_NAME,
          payment_id: null,
        },
      ];
      return withFlags({
        ...current,
        proofs,
        status: "proof_received",
        has_pending_proof: true,
        proof_received_at: now,
        history: [
          {
            at: now,
            code: "payment_doc.attached",
            text: "Приложена платёжка клиента",
            by: ACCOUNTANT_NAME,
          },
          ...current.history,
        ],
      });
    });
    return HttpResponse.json(next, { status: 201 });
  }),

  http.get("*/eds/payments/:id/proofs/:proofId/file", ({ params }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const card = findInvoice(Number(params["id"]));
    const proof = card?.proofs.find((p) => p.id === Number(params["proofId"]));
    if (!card || !proof) return notFound("Платёжка не найдена.");
    return new HttpResponse(`Демонстрационное содержимое платёжки «${proof.original_name}».`, {
      headers: {
        "content-type": "application/octet-stream",
        "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(proof.original_name)}`,
      },
    });
  }),

  http.post("*/eds/payments/:id/request-payment-doc", ({ params }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const card = findInvoice(Number(params["id"]));
    if (!card) return notFound("Счёт не найден.");
    if (!withFlags(card).can_request_proof) {
      return failure(409, "CONFLICT", "Счёт не ждёт оплаты.", "erp", {
        backend_status: 409,
        reason: "not_open",
      });
    }
    const now = new Date().toISOString();
    const next = update(card.id, (current) => ({
      ...current,
      payment_doc_requested_at: now,
      history: [
        {
          at: now,
          code: "payment_doc.requested",
          text: "Запрошена платёжка у клиента",
          by: ACCOUNTANT_NAME,
        },
        ...current.history,
      ],
    }));
    return HttpResponse.json(next && withFlags(next));
  }),

  // --- служебки к оплате ----------------------------------------------------------------------

  http.get("*/eds/payment-memos", ({ request }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const url = new URL(request.url);
    const wanted = (url.searchParams.get("status") ?? "to_pay") as PaymentMemoStatus;
    const found = readMemos()
      .filter((m) => isPayable(m) && MEMO_STATUS(m) === wanted)
      .map(memoRow);
    const page: PaymentMemoPage = paged(url, found);
    return HttpResponse.json(page);
  }),

  http.get("*/eds/payment-memos/:id", ({ params }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const memo = readMemos().find((m) => m.id === String(params["id"]) && m.kind === "memo");
    if (!memo) return notFound("Служебная записка не найдена.", "eds");
    return HttpResponse.json(memoCard(memo, ok.who));
  }),

  http.post("*/eds/payment-memos/:id/pay", async ({ request, params }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const body = (await request.json()) as PaymentMemoPayIn;
    if (dec(body.amount) <= 0) return validationBff("amount");
    if (!body.paid_on || body.paid_on > TODAY) return validationBff("paid_on");
    const memo = readMemos().find((m) => m.id === String(params["id"]) && m.kind === "memo");
    if (!memo?.amount) return notFound("Служебная записка не найдена.", "eds");
    const existing = memoPayments.get(memo.id);
    if (existing) {
      const same =
        existing.paid_on === body.paid_on &&
        existing.amount.amount === body.amount &&
        existing.amount.currency === body.currency;
      if (same) return HttpResponse.json(memoCard(memo, ok.who));
      return failure(409, "CONFLICT", "Записка уже оплачена.", "eds", {
        backend_status: 409,
        reason: "already_paid",
      });
    }
    if (!memo.accountant_step || MEMO_STATUS(memo) !== "to_pay") {
      return failure(409, "CONFLICT", "Записка не передана бухгалтеру.", "eds", {
        backend_status: 409,
        reason: "invalid_state",
      });
    }
    if (ok.who.crmId !== undefined && memo.author.crm_user_id === ok.who.crmId) {
      return failure(403, "FORBIDDEN", "Сейчас решение за другим сотрудником.", "eds", {
        backend_status: 403,
        reason: "not_your_step",
      });
    }
    if (body.currency !== memo.amount.currency || dec(body.amount) > dec(memo.amount.amount)) {
      const reason =
        body.currency !== memo.amount.currency ? "currency_mismatch" : "exceeds_approved";
      return failure(422, "VALIDATION_FAILED", "Сумма оплаты не принята.", "eds", {
        backend_status: 422,
        fields: ["amount"],
        messages: { amount: reason },
      });
    }
    const now = new Date().toISOString();
    memoPayments.set(memo.id, {
      paid_on: body.paid_on,
      amount: money(body.amount, body.currency),
      receipt_file_id: body.receipt_file_id ?? null,
      note: body.note ?? null,
      paid_by: ACCOUNTANT_PERSON,
      recorded_at: now,
    });
    const receipt = body.receipt_file_id ? receiptFiles.get(body.receipt_file_id) : undefined;
    const closed: MemoApprovalCard = {
      ...memo,
      document_status: "paid",
      status: "approved",
      accountant_step: false,
      can_decide: false,
      allowed_decisions: [],
      files: receipt ? [...memo.files, receipt] : memo.files,
      steps: memo.steps.map((s) =>
        s.status === "current"
          ? { ...s, status: "approved", decided_by: ACCOUNTANT_PERSON, decided_at: now }
          : s,
      ),
      decisions: [
        ...memo.decisions,
        {
          round: memo.round,
          step: memo.steps.length,
          decision: "approve",
          comment: body.note ?? null,
          by: ACCOUNTANT_PERSON,
          at: now,
        },
      ],
      updated_at: now,
    };
    writeMemos(readMemos().map((m) => (m.id === memo.id ? closed : m)));
    return HttpResponse.json(memoCard(closed, ok.who));
  }),

  http.post("*/eds/payment-receipt-files", async ({ request }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const file = await uploadedFile(request);
    if (!file) {
      return failure(422, "VALIDATION_FAILED", "Файл нужно передать формой multipart.", "bff", {
        fields: ["file"],
        reason: "multipart_required",
      });
    }
    if (file.size > 25 * 1024 * 1024) {
      return failure(413, "PAYLOAD_TOO_LARGE", "Файл больше 25 МБ.", "bff", {
        max_bytes: 25 * 1024 * 1024,
      });
    }
    if (EXT_BAD.test(file.name)) {
      return failure(
        415,
        "UNSUPPORTED_MEDIA_TYPE",
        "Допустимы PDF, изображения и документы Office.",
        "eds",
      );
    }
    const stored: EdsFile = {
      id: newReceiptId(),
      name: file.name,
      content_type: file.type || "application/octet-stream",
      size: file.size,
    };
    receiptFiles.set(stored.id, stored);
    return HttpResponse.json(stored, { status: 201 });
  }),
];
