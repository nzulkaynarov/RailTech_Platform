import { Button, Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { EdsRouteStep, QuoteApprovalCard } from "../../../shared/api/generated/model";
import { useGetQuoteApproval } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { History, type HistoryItem } from "../../../shared/ui/History";
import { LockIcon } from "../../../shared/ui/icons";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { RequestSteps } from "../../../shared/ui/RequestSteps";
import { SourceBanner } from "../../../shared/ui/SourceBanner";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { ApprovalSlot } from "./ApprovalPanel";
import { quoteRef } from "./api";
import { useStateLabels } from "./labels";
import { QuoteStatusTag } from "./QuoteStatus";
import { InternalBlock, QuoteLines } from "./QuoteParts";

function stepState(status: EdsRouteStep["status"]): HistoryItem["state"] {
  if (status === "current") return "waiting";
  if (status === "pending") return "todo";
  return "done";
}

function Route({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const { date } = useFormat();
  const items: HistoryItem[] = quote.steps.map((step) => ({
    state: stepState(step.status),
    title: t(`card.routeStep.${step.status}`, { label: step.label }),
    meta: (
      <>
        {step.decided_at && step.decided_by
          ? `${date(step.decided_at, "datetime")} · ${step.decided_by.full_name}`
          : null}
        {step.comment ? <p className="pf-dec-note">{step.comment}</p> : null}
      </>
    ),
  }));
  return <History items={items} label={t("card.route")} />;
}

function Requisites({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const { date } = useFormat();
  return (
    <DefinitionList
      items={[
        { label: t("card.fields.client"), value: quote.client_name },
        {
          label: t("card.fields.request"),
          value: quote.request ? (
            <>
              <Link className="pf-focusable" to={quote.request.path}>
                {quote.request.number}
              </Link>
              {quote.request.title ? <div className="pf-hint">{quote.request.title}</div> : null}
            </>
          ) : null,
        },
        {
          label: t("card.fields.letter"),
          value: quote.letter ? (
            <Link className="pf-focusable" to={quote.letter.path}>
              {quote.letter.number}
            </Link>
          ) : null,
        },
        {
          label: t("card.fields.calculatedBy"),
          value:
            quote.calculated_by.length > 0 ? (
              <ul className="pf-dec-list">
                {quote.calculated_by.map((c) => (
                  <li key={`${c.zone}-${c.name}`}>
                    {c.name} <span className="pf-hint">· {t(`card.zones.${c.zone}`)}</span>
                  </li>
                ))}
              </ul>
            ) : null,
        },
        {
          label: t("card.fields.date"),
          value: date(quote.ready_at ?? quote.created_at, "datetime"),
        },
        { label: t("card.fields.due"), value: quote.due ? date(quote.due) : null },
        { label: t("card.fields.outgoing"), value: quote.outgoing_number },
      ]}
    />
  );
}

function Content({
  quote,
  refKey,
  refetch,
}: {
  quote: QuoteApprovalCard;
  refKey: string;
  refetch: () => void;
}) {
  const { t } = useTranslation("quotes");
  const { me } = useAuth();
  const { wide, mobile } = useViewport();
  const [, setParams] = useSearchParams();
  const mayDecide = canEdit(me, "eds.drafts");
  const waiting = quote.status === "open" && quote.can_decide && mayDecide;

  const openApproval = () => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        // Телефон — лист на весь экран, планшет — окно справа (Drawer каркаса).
        if (mobile) next.set("sheet", "approve");
        else next.set("panel", "open");
        next.set("tab", "approve");
        return next;
      },
      { replace: true },
    );
  };

  return (
    <div className="pf-dec-page">
      <PageHeader
        title={t("card.title", { number: quote.number })}
        subtitle={t("card.version", { version: quote.version })}
        extra={
          <div className="pf-dec-row">
            <QuoteStatusTag quote={quote} />
            {quote.approved_late ? <StatusTag tone="gold">{t("card.lateTag")}</StatusTag> : null}
            {quote.outgoing_number ? (
              <StatusTag tone="blue">{quote.outgoing_number}</StatusTag>
            ) : null}
            {mayDecide ? null : (
              <StatusTag tone="default">
                <span className="pf-dec-lock">
                  <LockIcon size={12} />
                  {t("card.readOnly")}
                </span>
              </StatusTag>
            )}
          </div>
        }
      />
      <SourceBanner sources={quote.sources} onRetry={refetch} />
      <section className="pf-card pf-dec-steps" aria-label={t("card.steps")}>
        <RequestSteps
          stage={quote.stage}
          {...(quote.request ? { number: quote.request.number } : {})}
        />
      </section>
      {waiting && !wide ? (
        <div>
          <Button type="primary" onClick={openApproval}>
            {t("card.approve")}
          </Button>
        </div>
      ) : null}
      {quote.status === "open" && !waiting ? (
        <p className="pf-hint">{t("card.readOnlyHint")}</p>
      ) : null}
      <div className="pf-dec-grid pf-dec-grid--quote">
        <div className="pf-dec-main">
          <Card size="small" title={<h2 className="pf-dec-title">{t("card.lines")}</h2>}>
            <QuoteLines quote={quote} />
          </Card>
          <InternalBlock quote={quote} />
          <Card size="small" title={<h2 className="pf-dec-title">{t("card.route")}</h2>}>
            <Route quote={quote} />
          </Card>
        </div>
        <aside className="pf-dec-side" aria-label={t("card.requisites")}>
          <Card size="small" title={<h2 className="pf-dec-title">{t("card.requisites")}</h2>}>
            <Requisites quote={quote} />
          </Card>
        </aside>
      </div>
      <ApprovalSlot quoteRef={refKey} />
    </div>
  );
}

/** Карточка КП на одобрение (SPEC-v3 §7.3): шкала 7 шагов, реквизиты, состав и итоги, внутренний блок (маржа), маршрут; «Одобрение» — в боковом окне. */
export function QuoteView({ objectId }: { objectId: string }) {
  const { t } = useTranslation("quotes");
  const query = useGetQuoteApproval(quoteRef(objectId));
  const labels = useStateLabels();
  useDocumentTitle(t("card.title", { number: query.data?.number ?? objectId }));

  const error = query.error;
  if (error instanceof ApiError && error.status === 404) {
    return (
      <EmptyState
        title={t("state.notFound.title")}
        text={t("state.notFound.text")}
        action={<LinkButton to="/eds/drafts">{t("state.notFound.action")}</LinkButton>}
      />
    );
  }
  if (
    error instanceof ApiError &&
    error.status === 403 &&
    error.details["reason"] === "eds_not_granted"
  ) {
    return <EmptyState title={t("state.notGranted.title")} text={t("state.notGranted.text")} />;
  }
  if (query.isPending) {
    return (
      <div className="pf-dec-page">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    );
  }
  return (
    <QueryState query={query} labels={labels}>
      {(quote) => (
        <Content
          quote={quote}
          refKey={objectId}
          refetch={() => {
            void query.refetch();
          }}
        />
      )}
    </QueryState>
  );
}
