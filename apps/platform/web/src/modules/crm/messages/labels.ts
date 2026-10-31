import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";
import type { HandoffFacts } from "../../../shared/api/generated/model";

const KNOWN_REASONS = new Set([
  "human_requested",
  "callback_requested",
  "price_or_contract_asked",
  "negative_sentiment",
  "complaint",
  "kb_gap_streak",
  "no_progress",
  "competitor_mentioned",
  "high_score",
  "qualifier_recommend",
  "document_not_found",
  "service_request",
  "attachment_received",
  "agent_unavailable",
  "stop_word",
]);
const KNOWN_CHANNELS = new Set(["telegram", "web", "email", "phone", "referral"]);

/** Причины передачи словами; неизвестный код CRM — «Другая причина», без сырого кода в интерфейсе. */
export function reasonLabels(t: TFunction, codes: readonly string[]): string[] {
  const words = codes.map((code) =>
    t(`messages:reasons.${KNOWN_REASONS.has(code) ? code : "other"}`),
  );
  return [...new Set(words)];
}

export function channelLabel(t: TFunction, channel: string): string {
  return t(`messages:channels.${KNOWN_CHANNELS.has(channel) ? channel : "other"}`);
}

/** Факты квалификации строками «подпись: значение»; пустые не показываются. */
export function factRows(t: TFunction, facts: HandoffFacts): { label: string; value: string }[] {
  const rows: { label: string; value: string }[] = [];
  const add = (label: string, value: string | null | undefined) => {
    if (value) rows.push({ label: t(`messages:note.${label}`), value });
  };
  add("interest", facts.interest.join(", "));
  add("timeline", facts.timeline ? t(`messages:timeline.${facts.timeline}`) : null);
  add("role", facts.decision_role ? t(`messages:roles.${facts.decision_role}`) : null);
  add("budget", facts.budget_hint);
  add("company", facts.company);
  add("companySize", facts.company_size);
  add("region", facts.region);
  return rows;
}

/** Текст отказа действия: подкод CRM (`details.reason`), затем код BFF, затем общий. */
export function actionError(t: TFunction, error: unknown): string {
  if (!(error instanceof ApiError)) return t("messages:errors.generic");
  const reason = error.details["reason"];
  if (reason === "lead_taken") {
    const name = error.details["assigned_user_name"];
    return typeof name === "string" && name
      ? t("messages:errors.lead_taken", { name })
      : t("messages:errors.lead_taken_unknown");
  }
  if (typeof reason === "string") {
    const key = `messages:errors.${reason}`;
    const text = t(key, { defaultValue: "" });
    if (text) return text;
  }
  const byCode = t(`messages:errors.${error.code}`, { defaultValue: "" });
  return byCode || t("messages:errors.generic");
}

/** Итог неудачной отправки ответа: текст для сотрудника и можно ли «Повторить» с тем же ключом. */
export interface SendFailure {
  text: string;
  retry: boolean;
  /** Итог отправки неизвестен: правка текста создаст новое сообщение (новый ключ) */
  unknown?: boolean;
}

/**
 * Telegram не ответил (502 `INTEGRATION_FAILED`, `delivery_failed`) — «Не отправлено: Telegram не ответил»; CRM не ответила
 * (`BACKEND_UNAVAILABLE`, сеть) — «CRM не отвечает»; ответ ещё отправляется (409 `reply_in_progress`) — «ещё отправляется».
 * Во всех трёх «Повторить» безопасно: ключ повтора тот же, CRM не продублирует сообщение. Прочие отказы — без повтора.
 */
export function sendFailure(t: TFunction, error: unknown): SendFailure {
  if (!(error instanceof ApiError))
    return { text: t("messages:errors.BACKEND_UNAVAILABLE"), retry: true };
  const reason = error.details["reason"];
  if (reason === "reply_in_progress")
    return { text: t("messages:errors.reply_in_progress"), retry: true };
  if (reason === "delivery_unknown")
    return { text: t("messages:errors.delivery_unknown"), retry: true, unknown: true };
  if (reason === "delivery_unconfirmed")
    return { text: t("messages:thread.delivery.unconfirmedFinal"), retry: false };
  if (error.code === "INTEGRATION_FAILED")
    return { text: t("messages:composer.failed"), retry: true };
  if (error.code === "BACKEND_UNAVAILABLE" || error.status >= 500)
    return { text: t("messages:errors.BACKEND_UNAVAILABLE"), retry: true };
  return { text: actionError(t, error), retry: false };
}
