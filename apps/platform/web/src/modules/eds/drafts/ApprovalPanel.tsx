import { type ReactNode, useEffect } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { QuoteApprovalCard } from "../../../shared/api/generated/model";
import { useGetQuoteApproval } from "../../../shared/api/generated/platform-bff";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { quoteRef } from "./api";
import { ApprovalForm } from "./ApprovalForm";
import { clearDraft } from "./draft";
import { useStateLabels } from "./labels";

function PanelBody({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const { me } = useAuth();
  // Заместитель решает шаг замещаемого и с разделом «только чтение» (СЦ-9): право и замещение проверяет EDS
  const mayDecide = canEdit(me, "eds.drafts") || Boolean(quote.acting_for);
  // КП уже решено (в том числе другим) или заменено новой версией: черновик ему не нужен.
  useEffect(() => {
    if (quote.status !== "open") clearDraft(me.id, quote.id);
  }, [quote.status, quote.id, me.id]);
  let body: ReactNode;
  if (quote.status === "open" && quote.can_decide && mayDecide) {
    body = <ApprovalForm quote={quote} />;
  } else if (quote.status === "open") {
    body = (
      <EmptyState
        level={3}
        compact
        title={t("panel.openReadOnly.title")}
        text={t("panel.openReadOnly.text")}
      />
    );
  } else {
    // Решённое КП говорит о себе статусом в шапке и лентой «Маршрут» (ЕД-7)
    body = null;
  }
  return <div className="pf-dec-panel pf-dec-page">{body}</div>;
}

/** Блок решения в центре карточки КП: форма для директора или пояснение, почему решает не он (ЕД-7). */
export function ApprovalPanel({ quoteRef: ref }: { quoteRef: string }) {
  const query = useGetQuoteApproval(quoteRef(ref));
  const labels = useStateLabels();
  return (
    <QueryState query={query} labels={labels} level={3} compact>
      {(quote) => <PanelBody quote={quote} />}
    </QueryState>
  );
}
