import type {
  PaymentCard,
  PaymentDisplayStatus,
  PaymentMoney,
  PaymentRow,
} from "../../../shared/api/generated/model";

/** Вкладки «Счетов и оплат» (SPEC-v3 §7.3) плюс «Все счета»: параметр адреса `?show=`. */
export const TABS = ["to_issue", "awaiting", "proofs", "overdue", "memos", "all"] as const;
export type ShowTab = (typeof TABS)[number];
export type InvoiceTab = Exclude<ShowTab, "memos">;

export function showTab(value: string | null): ShowTab {
  return (TABS as readonly string[]).includes(value ?? "") ? (value as ShowTab) : "awaiting";
}

export const PAGE = 25;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isUuid = (value: string): boolean => UUID.test(value);
export const isNumericId = (value: string): boolean => /^\d{1,9}$/.test(value);

/** Карточка счёта (целый id ERP) и служебки к оплате (UUID документа EDS) — один раздел, разные адреса. */
export const invoicePath = (id: number): string => `/eds/payments/${String(id)}`;
export const memoPath = (id: string): string => `/eds/payments/${id}`;

/** Статусы счёта со своим словом раздела (`payments:status.*`): «не выставлен» и «отменён»; остальные — словарь SPEC-v3 §2.4. */
export const OWN_STATUS_WORDS: ReadonlySet<PaymentDisplayStatus> = new Set(["draft", "cancelled"]);

/** Счёт ждёт денег: можно подтверждать оплату и прикладывать платёжки. */
export function isOpen(status: PaymentDisplayStatus): boolean {
  return status !== "paid" && status !== "draft" && status !== "cancelled";
}

export function moneyProps(money: PaymentMoney): { value: string; currency: string } {
  return { value: money.amount, currency: money.currency };
}

/** Действие в строке таблицы: платёжку проверяют, остальное — подтверждают оплату или открывают. */
export function rowAction(row: PaymentRow): "confirm" | "review" | "open" {
  if (row.status === "proof_received") return "review";
  if (isOpen(row.status)) return "confirm";
  return "open";
}

/**
 * Сумма из поля ввода в вид контракта `1500000.00`: пробелы (в том числе неразрывные) убираются, запятая — десятичный
 * разделитель, не больше двух знаков после него. Нечисловое и неположительное — `null`.
 */
export function normalizeAmount(input: string): string | null {
  const text = input.replace(/\s/g, "").replace(",", ".");
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(text)) return null;
  const [whole = "0", fraction = ""] = text.split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (cents <= 0n) return null;
  return `${whole.replace(/^0+(?=\d)/, "")}.${fraction.padEnd(2, "0")}`;
}

/** Копейки целым числом из суммы контракта (`112000000.00`): сравнение без плавающей точки. */
export function toCents(amount: string): bigint {
  const [whole = "0", fraction = ""] = amount.split(".");
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0").slice(0, 2));
}

export function fromCents(cents: bigint): string {
  const abs = cents < 0n ? -cents : cents;
  return `${cents < 0n ? "-" : ""}${(abs / 100n).toString()}.${(abs % 100n).toString().padStart(2, "0")}`;
}

/** Ключ повтора: один на попытку отправки формы (ERP отдаёт прежний ответ при повторе с тем же ключом). */
export function newKey(): string {
  const random = globalThis.crypto as Crypto | undefined;
  return random?.randomUUID
    ? random.randomUUID()
    : `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Остаток после платежа `amount` (копейки) — строкой контракта. */
export function remainderAfter(card: Pick<PaymentCard, "balance">, amount: string): string {
  return fromCents(toCents(card.balance.amount) - toCents(amount));
}
