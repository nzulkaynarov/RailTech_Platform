import type {
  EdsFile,
  PaymentCard,
  PaymentCounts,
  PaymentDisplayStatus,
  PaymentHistoryEntry,
  PaymentMemoPayment,
  PaymentMoney,
  PaymentProof,
  PaymentRecord,
  PaymentRow,
} from "../../shared/api/generated/model";

/**
 * Вымышленные счета и платёжки для MSW (D2-4, BFF 0.26.0): те же формы, что вернёт BFF по `platform-bff.yaml`. Названия
 * компаний выдуманы (репозиторий публичный). Состояние живёт в памяти страницы: «Подтвердить оплату» меняет остаток и
 * статус, следующий запрос списка и карточки его видит; `resetPayments()` возвращает исходное (тесты).
 */
/** День, от которого считаются просрочки вымышленной доски (стабильные «просрочен на 8 дн.» в тестах и на демо). */
export const TODAY = "2026-10-28";

/**
 * Сегодня по часам компании (Asia/Tashkent) — как у BFF при проверке «дата не в будущем». Форма предлагает настоящую
 * сегодняшнюю дату, поэтому сверять её с замороженным `TODAY` нельзя: со следующего дня каждое подтверждение падало бы
 * в «проверьте сумму и дату».
 */
export function companyToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tashkent",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

const money = (amount: string, currency = "UZS"): PaymentMoney => ({ amount, currency });

export const dec = (value: string): number => Math.round(Number(value) * 100);
export const fromCents = (cents: number): string => (cents / 100).toFixed(2);

interface Seed {
  id: number;
  number: string;
  deal: number;
  client: string;
  total: string;
  paid?: string;
  issued: string | null;
  due: string | null;
  draft?: boolean;
  proofs?: PaymentProof[];
  items?: [string, number, string][];
}

const CABINET_PROOF: PaymentProof = {
  id: 5,
  source: "CABINET",
  status: "PENDING",
  original_name: "платёжка-0127.pdf",
  claimed_amount: "28000000.00",
  claimed_date: "2026-10-27",
  note: "",
  received_at: "2026-10-27T15:00:00Z",
  recorded_by: null,
  payment_id: null,
};

const SEEDS: readonly Seed[] = [
  {
    id: 142,
    number: "СЧ-2026/142",
    deal: 104,
    client: "ООО «Демо-Рейл»",
    total: "112000000.00",
    issued: "2026-10-20",
    due: "2026-11-07",
    items: [["Привод стрелочный СП-6", 12, "8333333.33"]],
  },
  {
    id: 143,
    number: "СЧ-2026/143",
    deal: 107,
    client: "АО «Тест-Логистика»",
    total: "36400000.00",
    issued: null,
    due: null,
    draft: true,
    items: [["Шефмонтаж", 1, "32500000.00"]],
  },
  {
    id: 144,
    number: "СЧ-2026/144",
    deal: 101,
    client: "ООО «Пример-Транс»",
    total: "45600000.00",
    issued: "2026-10-05",
    due: "2026-10-20",
    items: [["Комплект крепежа КБ-65", 400, "101785.71"]],
  },
  {
    id: 145,
    number: "СЧ-2026/145",
    deal: 99,
    client: "ООО «Север-Путь»",
    total: "28000000.00",
    issued: "2026-10-22",
    due: "2026-11-05",
    proofs: [CABINET_PROOF],
    items: [["Накладка стыковая Р65", 800, "31250.00"]],
  },
  {
    id: 146,
    number: "СЧ-2026/146",
    deal: 97,
    client: "ООО «Демо-Рейл»",
    total: "9800000.00",
    paid: "9800000.00",
    issued: "2026-09-30",
    due: "2026-10-14",
    items: [["Проектные работы", 1, "8750000.00"]],
  },
  {
    id: 147,
    number: "СЧ-2026/147",
    deal: 95,
    client: "АО «Тест-Логистика»",
    total: "50000000.00",
    paid: "20000000.00",
    issued: "2026-10-12",
    due: "2026-11-12",
    items: [["Стрелочный перевод проекта 2764", 2, "22321428.57"]],
  },
];

export function statusOf(
  card: Pick<PaymentCard, "amount" | "paid" | "due_date" | "proofs" | "issued_at">,
  draft: boolean,
): PaymentDisplayStatus {
  const total = dec(card.amount.amount);
  const paid = dec(card.paid.amount);
  if (draft) return "draft";
  if (paid >= total) return "paid";
  if (card.proofs.some((p) => p.status === "PENDING")) return "proof_received";
  if (card.due_date && card.due_date < TODAY) return "overdue";
  return paid > 0 ? "partially_paid" : "issued";
}

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

function build(seed: Seed): PaymentCard {
  const total = dec(seed.total);
  const paid = dec(seed.paid ?? "0");
  const subtotal = Math.round(total / 1.12);
  const payments: PaymentRecord[] =
    paid > 0
      ? [
          {
            id: seed.id * 10,
            amount: fromCents(paid),
            paid_at: "2026-10-15",
            method: "BANK_TRANSFER",
            reference: `BANK-${String(seed.id)}`,
            receipt_number: `RCP-${String(seed.id)}`,
            has_proof: false,
            recorded_by: ACCOUNTANT_NAME,
            created_at: "2026-10-15T10:00:00Z",
          },
        ]
      : [];
  const history: PaymentHistoryEntry[] = payments.map((p) => ({
    at: p.created_at,
    code: "payment.recorded",
    text: "Зафиксирован платёж",
    by: ACCOUNTANT_NAME,
  }));
  const proofs = seed.proofs ?? [];
  const partial = {
    amount: money(fromCents(total)),
    paid: money(fromCents(paid)),
    due_date: seed.due,
    issued_at: seed.issued,
    proofs,
  };
  const status = statusOf(partial, seed.draft ?? false);
  return {
    id: seed.id,
    number: seed.number,
    project_number: `ПР-2026-${String(seed.deal).padStart(3, "0")}`,
    deal_id: seed.deal,
    client_name: seed.client,
    amount: money(fromCents(total)),
    paid: money(fromCents(paid)),
    balance: money(fromCents(total - paid)),
    issued_at: seed.issued,
    due_date: seed.due,
    status,
    days_overdue: status === "overdue" && seed.due ? daysBetween(seed.due, TODAY) : null,
    has_pending_proof: proofs.some((p) => p.status === "PENDING"),
    proof_received_at: proofs.find((p) => p.status === "PENDING")?.received_at ?? null,
    subtotal: fromCents(subtotal),
    vat: fromCents(total - subtotal),
    notes: "",
    has_pdf: !seed.draft,
    items: (seed.items ?? []).map(([description, quantity, unit]) => ({
      description,
      quantity,
      unit_price: unit,
      total: fromCents(dec(unit) * quantity),
    })),
    payments,
    proofs,
    history,
    payment_doc_requested_at: null,
    can_confirm: !seed.draft && paid < total,
    can_attach_proof: !seed.draft && paid < total,
    can_request_proof: !seed.draft && paid < total,
    replayed: false,
  };
}

export const ACCOUNTANT_NAME = "Демо Бухгалтеров";

let cards = SEEDS.map(build);
export const readInvoices = (): PaymentCard[] => cards;
export const writeInvoices = (next: PaymentCard[]): void => {
  cards = next;
};
export const findInvoice = (id: number): PaymentCard | undefined => cards.find((c) => c.id === id);

/** Идемпотентные ответы по `Idempotency-Key` (как кэш ERP): повтор отдаёт прежнее тело. */
export const idempotent = new Map<string, PaymentCard>();
let nextProof = 50;
export const newProofId = (): number => ++nextProof;

export function resetPayments(): void {
  cards = SEEDS.map(build);
  idempotent.clear();
  nextProof = 50;
  resetMemoPayments();
}

export type Tab = "to_issue" | "awaiting" | "proofs" | "overdue" | "all";

export function tabOf(card: PaymentCard): Exclude<Tab, "all"> | null {
  switch (card.status) {
    case "draft":
      return "to_issue";
    case "proof_received":
      return "proofs";
    case "overdue":
      return "overdue";
    case "issued":
    case "partially_paid":
      return "awaiting";
    default:
      return null;
  }
}

export function counts(): PaymentCounts {
  const base: PaymentCounts = { to_issue: 0, awaiting: 0, proofs: 0, overdue: 0 };
  for (const card of cards) {
    const tab = tabOf(card);
    if (tab) base[tab] += 1;
  }
  return base;
}

export function rowOf(card: PaymentCard): PaymentRow {
  return {
    id: card.id,
    number: card.number,
    project_number: card.project_number,
    deal_id: card.deal_id,
    client_name: card.client_name,
    amount: card.amount,
    paid: card.paid,
    balance: card.balance,
    issued_at: card.issued_at,
    due_date: card.due_date,
    status: card.status,
    days_overdue: card.days_overdue,
    has_pending_proof: card.has_pending_proof,
    proof_received_at: card.proof_received_at,
  };
}

// --- служебки к оплате --------------------------------------------------------------------------

/** Оплата служебки: `id документа` → факт оплаты (EDS хранит его в `DocumentPayment`). */
export const memoPayments = new Map<string, PaymentMemoPayment>();
/** Платёжки бухгалтера, загруженные до «Оплачено»: `id файла` → файл EDS. */
export const receiptFiles = new Map<string, EdsFile>();
let nextReceipt = 0;
export const newReceiptId = (): string => {
  nextReceipt += 1;
  return `72000000-0000-4000-8000-${String(nextReceipt).padStart(12, "0")}`;
};

export function resetMemoPayments(): void {
  memoPayments.clear();
  receiptFiles.clear();
  nextReceipt = 0;
}
