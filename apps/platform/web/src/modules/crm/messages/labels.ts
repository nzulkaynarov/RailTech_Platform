import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";
import type { HandoffFacts, HandoffInfoPriority } from "../../../shared/api/generated/model";
import type { StatusTone } from "../../../shared/lib/statuses";

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

export const PRIORITY_TONE: Record<HandoffInfoPriority, StatusTone> = {
  hot: "red",
  warm: "gold",
  info: "default",
};

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

/** Отправка не прошла, потому что Telegram не ответил (502 `INTEGRATION_FAILED`, `delivery_failed`) или CRM не ответила. */
export function isDeliveryFailure(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return (
    error.code === "INTEGRATION_FAILED" ||
    error.code === "BACKEND_UNAVAILABLE" ||
    error.status >= 500
  );
}
