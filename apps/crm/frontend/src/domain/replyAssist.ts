import type { AssistOut } from "../api/generated/model";
import { t } from "../i18n/ru";

/** ИИ-помощь при ответе (Q-019): «Черновик» и «Улучшить» — только по кнопке, без отправки. */
export type AssistMode = "draft" | "improve";

/** «Улучшить» нужен написанный текст; «Черновик» доступен всегда. */
export function canAssist(mode: AssistMode, draft: string): boolean {
  return mode === "draft" || draft.trim() !== "";
}

/** Черновик заменяет написанное — только после подтверждения. */
export function needsReplaceConfirm(mode: AssistMode, draft: string): boolean {
  return mode === "draft" && draft.trim() !== "";
}

export type AssistApplied = {
  /** Новый текст поля ответа. */
  text: string;
  /** Что вернуть по «Отменить» (только после «Улучшить», если текст изменился). */
  undo: string | null;
  /** Пояснение для менеджера. */
  info: string;
};

/** Как ответ сервера меняет поле ответа. */
export function applyAssist(mode: AssistMode, before: string, out: AssistOut): AssistApplied {
  const changed = out.text !== before;
  const undo = mode === "improve" && changed ? before : null;
  if (out.notice === "numbers_removed")
    return { text: out.text, undo, info: t.lead.assist.numbersRemoved };
  if (out.notice === "new_numbers")
    return { text: before, undo: null, info: t.lead.assist.newNumbers };
  return { text: out.text, undo, info: t.lead.assist.ready };
}
