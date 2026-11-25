import type {
  LetterIntakeFields,
  LetterIntakeSuggestion,
  LetterKind,
} from "../../../shared/api/generated/model";
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
    // корреспондент уже выбран из контрагентов (СУЩ-2.6): название и ИНН — из его карточки
    if ((key === "senderName" || key === "senderInn") && next.senderCompanyId !== "") continue;
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

/** Поля, которые посчитал код, а не модель (`by_code` ответа): помечаются «Из текста письма», не «Предложено ИИ». */
export function byCodeFields(suggestion: LetterIntakeSuggestion): AiField[] {
  const names: Record<string, AiField> = { sender_inn: "senderInn", document_due: "documentDue" };
  return (suggestion.by_code ?? []).flatMap((name) => (names[name] ? [names[name]] : []));
}

/** Дата поступления годится для отсчёта срока на сервере: не из будущего и не старше года (иначе 422). */
export function usableReceivedAt(value: string, today: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value > today) return false;
  const floor = new Date(`${today}T00:00:00Z`);
  floor.setUTCFullYear(floor.getUTCFullYear() - 1);
  return value >= floor.toISOString().slice(0, 10);
}

/** Какой текст у плашки «Заполнено из файла»: всё посчитал код, смесь с ответом модели или всё предложила модель. */
export function bannerKind(
  left: ReadonlySet<AiField>,
  byCode: ReadonlySet<AiField>,
): "ai" | "rules" | "mixed" {
  const code = [...left].filter((key) => byCode.has(key)).length;
  if (code === 0) return "ai";
  return code === left.size ? "rules" : "mixed";
}
