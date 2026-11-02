import { useTranslation } from "react-i18next";

import type { QuoteApprovalCard } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { DocumentStatusTag } from "../documents/status";

/**
 * Тег КП: пока ждёт решения — «Черновик · отправка заблокирована» (SPEC-v3 §7.3), дальше — слово статуса маршрута.
 * Версию заменила более новая (D26G-2) — «Заменена версией N»: это история, решать по ней нечего.
 */
export function QuoteStatusTag({
  quote,
}: {
  quote: Pick<QuoteApprovalCard, "status"> & { superseded_by?: number | null };
}) {
  const { t } = useTranslation("quotes");
  if (quote.superseded_by) return <SupersededTag version={quote.superseded_by} />;
  if (quote.status === "open") {
    return (
      <StatusTag kind="quote" status="open">
        {t("card.draftTag")}
      </StatusTag>
    );
  }
  return <DocumentStatusTag kind="quote" status={quote.status} />;
}

/** «Заменена версией N»: версия КП в истории, решать по ней нечего (D26G-2). */
export function SupersededTag({ version }: { version: number }) {
  const { t } = useTranslation("quotes");
  return <StatusTag tone="default">{t("superseded", { version })}</StatusTag>;
}
