import type { LetterIntakeFields, LetterKind } from "../../../shared/api/generated/model";
import type { RegisterValues } from "./registerModel";

/**
 * «Заполнить из файла» (EDS-REG): что помощник предложил и что человек сделал с предложением. Предложение заполняет только
 * пустые поля (набранное человеком не перетирается); поле с предложением помечено «Предложено ИИ», пока его не поправили.
 * Решение для журнала: ничего не правили — `accepted`, правили — `edited`, отказались — `manual`.
 */
export type AiField =
  | "senderName"
  | "senderInn"
  | "refNumber"
  | "refDate"
  | "subject"
  | "summary"
  | "kind"
  | "documentDue";

const MAP: readonly (readonly [AiField, keyof LetterIntakeFields])[] = [
  ["senderName", "sender_name"],
  ["senderInn", "sender_inn"],
  ["refNumber", "sender_ref_number"],
  ["refDate", "sender_ref_date"],
  ["subject", "subject"],
  ["summary", "summary"],
  ["kind", "kind"],
  ["documentDue", "document_due"],
];

export function applySuggestion(
  values: RegisterValues,
  fields: LetterIntakeFields,
  kinds: readonly LetterKind[],
): { values: RegisterValues; filled: AiField[] } {
  const next: RegisterValues = { ...values };
  const filled: AiField[] = [];
  for (const [key, source] of MAP) {
    const suggested = fields[source];
    if (!suggested || next[key] !== "") continue;
    if (key === "kind" && !kinds.some((kind) => kind.code === suggested)) continue;
    next[key] = suggested;
    filled.push(key);
  }
  // Вид со «срочно» (требование ГНК) ставит «срочно», как при выборе вручную.
  if (filled.includes("kind") && kinds.find((kind) => kind.code === next.kind)?.urgent)
    next.urgent = true;
  return { values: next, filled };
}

/** Убрать предложенное: поля, которые человек не правил, снова пустые. */
export function revertSuggestion(
  values: RegisterValues,
  filled: readonly AiField[],
): RegisterValues {
  const next: RegisterValues = { ...values };
  for (const key of filled) next[key] = "";
  return next;
}

export function decisionOf(
  filled: readonly AiField[],
  left: ReadonlySet<AiField>,
): "accepted" | "edited" {
  return filled.every((key) => left.has(key)) ? "accepted" : "edited";
}
