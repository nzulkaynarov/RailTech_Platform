import type { useTranslation } from "react-i18next";

import type { AttentionItem } from "../../../shared/api/generated/model";

export function attentionTexts(
  t: ReturnType<typeof useTranslation>["t"],
  item: AttentionItem,
): { subject: string; detail: string | null } {
  const card = t(`cards.${item.card}.title`);
  switch (item.kind) {
    case "not_configured":
      return { subject: card, detail: t(`attention.notConfigured.${item.card}`) };
    case "model_problem": {
      const alias = t(`models.alias.${item.subject ?? ""}`, { defaultValue: item.subject ?? card });
      return { subject: alias, detail: t("health.model.problem", { alias }) };
    }
    case "backup_stale":
      return {
        subject: card,
        detail: [t("attention.backupStale"), item.detail].filter(Boolean).join(" "),
      };
    case "check_failed":
      return { subject: card, detail: t("attention.checkFailed") };
    case "rotation_pending":
      return { subject: card, detail: t("attention.rotationPending") };
    case "bot_not_running":
      return {
        subject: card,
        detail: [t("attention.botNotRunning"), item.detail].filter(Boolean).join(" "),
      };
    case "paused":
      return {
        subject: item.subject ?? card,
        detail: [t("attention.paused"), item.detail].filter(Boolean).join(" "),
      };
    case "budget_over":
    case "budget_near":
      return {
        subject: item.subject ?? card,
        detail: `${t(`attention.${item.kind}`)} ${item.detail ?? ""}`.trim(),
      };
    default:
      return { subject: item.subject ?? card, detail: item.detail };
  }
}
