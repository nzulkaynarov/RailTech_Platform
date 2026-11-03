import type {
  SupplierOrderLine,
  SupplierOrderReceiptInLinesItem,
} from "../../../shared/api/generated/model";
import { companyToday } from "../../../shared/lib/dates";

/** Прослеживаемость на приёмке (ADR-0021): черновик полей строки, разбор вставки и проверка до отправки. */
export interface TraceDraft {
  serials: string;
  lot: string;
  expiry: string;
  docNumber: string;
  docValidUntil: string;
}

export const EMPTY_TRACE: TraceDraft = {
  serials: "",
  lot: "",
  expiry: "",
  docNumber: "",
  docValidUntil: "",
};

export type TrackedLine = Pick<SupplierOrderLine, "tracking" | "requires_doc">;

/** Номера из вставки: по строкам, через запятую, точку с запятой или табуляцию. */
export function parseSerials(text: string): string[] {
  return text
    .split(/[\n,;\t]+/)
    .map((n) => n.trim())
    .filter(Boolean);
}

export const needsTracking = (line: TrackedLine) => line.tracking !== "none" || line.requires_doc;

/** Поля строки приёмки для ERP: только то, что требует категория. */
export function traceFields(
  line: TrackedLine,
  draft: TraceDraft,
): Partial<SupplierOrderReceiptInLinesItem> {
  const out: Partial<SupplierOrderReceiptInLinesItem> = {};
  if (line.tracking === "serial") out.serials = parseSerials(draft.serials);
  if (line.tracking === "lot") {
    out.lot = draft.lot.trim();
    if (draft.expiry) out.expiry_date = draft.expiry;
  }
  if (line.requires_doc) {
    out.doc_number = draft.docNumber.trim();
    if (draft.docValidUntil) out.doc_valid_until = draft.docValidUntil;
  }
  return out;
}

/** Чего не хватает строке (проверка до отправки — та же, что у сервера). */
export function traceProblem(
  line: TrackedLine,
  draft: TraceDraft,
  quantity: number,
): string | null {
  if (line.tracking === "serial") {
    const serials = parseSerials(draft.serials);
    if (serials.length !== quantity) return "serials";
    if (new Set(serials).size !== serials.length) return "serialsRepeat";
  }
  if (line.tracking === "lot" && !draft.lot.trim()) return "lot";
  if (line.requires_doc && (!draft.docNumber.trim() || !draft.docValidUntil)) return "doc";
  if (line.requires_doc && draft.docValidUntil < companyToday()) return "docExpired";
  return null;
}
