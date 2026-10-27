import { type ReactNode, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { QuoteApprovalCard } from "../../../shared/api/generated/model";
import { useGetQuoteApproval } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { DecisionSlot } from "../decision/DecisionSlot";
import { quotePath, quoteRef } from "./api";
import { ApprovalForm } from "./ApprovalForm";
import { clearDraft } from "./draft";
import { useStateLabels } from "./labels";
import { QuoteStatusTag } from "./QuoteStatus";

function Brief({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const { date } = useFormat();
  const total = quote.totals?.total;
  return (
    <section className="pf-dec-brief" aria-label={quote.number}>
      <div className="pf-dec-brief-head">
        <h3 className="pf-fp-title">{quote.number}</h3>
        <QuoteStatusTag quote={quote} />
      </div>
      <DefinitionList
        items={[
          { label: t("panel.brief.client"), value: quote.client_name },
          { label: t("panel.brief.request"), value: quote.request?.number },
          {
            label: t("panel.brief.total"),
            value: total ? (
              <MoneyText
                value={total}
                {...(quote.totals && quote.totals.currency !== "UZS"
                  ? { currency: quote.totals.currency }
                  : {})}
              />
            ) : null,
          },
          { label: t("panel.brief.due"), value: quote.due ? date(quote.due) : null },
        ]}
      />
      <Link className="pf-focusable pf-dec-open" to={quotePath(quote.number)}>
        {t("panel.briefOpen")}
      </Link>
    </section>
  );
}

function PanelBody({
  quote,
  variant,
  brief,
  onDone,
}: {
  quote: QuoteApprovalCard;
  variant: "panel" | "sheet";
  brief: boolean;
  onDone?: (() => void) | undefined;
}) {
  const { t } = useTranslation("quotes");
  const { me } = useAuth();
  const mayDecide = canEdit(me, "eds.drafts");
  // КП уже решено (в том числе другим) или заменено новой версией: черновик ему не нужен.
  useEffect(() => {
    if (quote.status !== "open") clearDraft(me.id, quote.id);
  }, [quote.status, quote.id, me.id]);
  let body: ReactNode;
  if (quote.status === "open" && quote.can_decide && mayDecide) {
    body = <ApprovalForm quote={quote} variant={variant} {...(onDone ? { onDone } : {})} />;
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
    body = (
      <EmptyState
        level={3}
        compact
        title={t(`panel.decided.${quote.status}.title`)}
        text={t(`panel.decided.${quote.status}.text`)}
      />
    );
  }
  return (
    <div className="pf-dec-panel pf-dec-page">
      {brief ? <Brief quote={quote} /> : null}
      {body}
    </div>
  );
}

/** Содержимое вкладки «Одобрение»: КП по `ref` (id или номер), форма для директора, пояснение остальным. */
export function ApprovalPanel({
  quoteRef: ref,
  brief = false,
  variant = "panel",
  onDone,
}: {
  quoteRef: string;
  brief?: boolean;
  variant?: "panel" | "sheet";
  onDone?: (() => void) | undefined;
}) {
  const query = useGetQuoteApproval(quoteRef(ref));
  const labels = useStateLabels();
  return (
    <QueryState query={query} labels={labels} level={3} compact>
      {(quote) => <PanelBody quote={quote} variant={variant} brief={brief} onDone={onDone} />}
    </QueryState>
  );
}

function SheetTitle({ quoteRef: ref }: { quoteRef: string }) {
  const { t } = useTranslation("quotes");
  const query = useGetQuoteApproval(quoteRef(ref));
  return (
    <>{query.data ? t("panel.sheetTitle", { number: query.data.number }) : t("panel.sheetLabel")}</>
  );
}

/** Где живёт «Одобрение» КП: вкладка бокового окна каркаса, на телефоне — лист на весь экран (`?sheet=approve`). */
export function ApprovalSlot({
  quoteRef: ref,
  brief = false,
}: {
  quoteRef: string;
  brief?: boolean;
}) {
  const { t } = useTranslation("quotes");
  return (
    <DecisionSlot
      tab="approve"
      sheet="approve"
      title={<SheetTitle quoteRef={ref} />}
      label={t("panel.sheetLabel")}
      closeLabel={t("panel.sheetClose")}
    >
      {(variant, onDone) => (
        <ApprovalPanel quoteRef={ref} brief={brief} variant={variant} onDone={onDone} />
      )}
    </DecisionSlot>
  );
}
