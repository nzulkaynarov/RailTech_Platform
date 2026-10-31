import { useTranslation } from "react-i18next";

import type { QuoteApprovalCard } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { DocumentStatusTag } from "../documents/status";

/** Тег КП: пока ждёт решения — «Черновик · отправка заблокирована» (SPEC-v3 §7.3), дальше — слово статуса маршрута. */
export function QuoteStatusTag({ quote }: { quote: Pick<QuoteApprovalCard, "status"> }) {
  const { t } = useTranslation("quotes");
  if (quote.status === "open") {
    return (
      <StatusTag kind="quote" status="open">
        {t("card.draftTag")}
      </StatusTag>
    );
  }
  return <DocumentStatusTag kind="quote" status={quote.status} />;
}
