import { Alert, Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { QuoteApprovalCard } from "../../../shared/api/generated/model";
import { useGetQuoteApproval } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { LockIcon } from "../../../shared/ui/icons";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { RequestSteps } from "../../../shared/ui/RequestSteps";
import { SourceBanner } from "../../../shared/ui/SourceBanner";
import { RouteTimeline } from "../../../shared/ui/RouteTimeline";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { DecisionCenter } from "../decision/DecisionCenter";
import { RecordTab } from "../decision/RecordTab";
import { ApprovalPanel } from "./ApprovalPanel";
import { quotePath, quoteRef } from "./api";
import { ClientDecisionCard } from "./ClientDecision";
import { ClientLinkCard } from "./ClientLink";
import { DeliveryReport } from "./DeliveryReport";
import { useStateLabels } from "./labels";
import { QuoteStatusTag } from "./QuoteStatus";
import { InternalBlock, QuoteLines } from "./QuoteParts";
import { PageFrame } from "../../../shared/ui/PageFrame";

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

/** «Обсуждение»: комментарии клиента к КП из кабинета (B-CABFIX-1); вкладка есть, только когда клиент что-то написал. */
function ClientComments({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const { date } = useFormat();
  if (quote.client_comments.length === 0) return null;
  return (
    <RecordTab tab="chat">
      <p className="pf-hint">{t("card.clientCommentsHint")}</p>
      <ol className="pf-dec-list" aria-label={t("card.clientCommentsList")}>
        {quote.client_comments.map((comment) => (
          <li key={`${comment.created_at}-${comment.author}`}>
            <div className="pf-hint">
              {comment.author_name ?? t("card.clientCommentAuthor")} ·{" "}
              {date(comment.created_at, "datetime")}
            </div>
            <p className="pf-dec-note">{comment.text}</p>
          </li>
        ))}
      </ol>
    </RecordTab>
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
  const mayDecide = canEdit(me, "eds.drafts") || Boolean(quote.acting_for);

  return (
    <PageFrame layout="object">
      <div className="pf-dec-page pf-overlay-aware">
        <PageHeader
          title={t("card.title", { number: quote.number })}
          subtitle={t("card.version", { version: quote.version })}
          extra={
            <div className="pf-dec-row">
              <QuoteStatusTag quote={quote} />
              {quote.approved_late ? <StatusTag tone="gold">{t("card.lateTag")}</StatusTag> : null}
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
        {quote.superseded_by ? (
          <Alert
            type="info"
            showIcon
            message={t("card.superseded", { version: quote.version, next: quote.superseded_by })}
            action={
              <Link className="pf-focusable" to={quotePath(quote.number)}>
                {t("card.supersededOpen", { next: quote.superseded_by })}
              </Link>
            }
          />
        ) : null}
        <section className="pf-card pf-dec-steps" aria-label={t("card.steps")}>
          <RequestSteps
            stage={quote.stage}
            {...(quote.request ? { number: quote.request.number } : {})}
          />
        </section>
        <ClientDecisionCard quote={quote} />
        <DeliveryReport quote={quote} />
        <ClientLinkCard quote={quote} />
        <Card size="small" title={<h2 className="pf-dec-title">{t("card.lines")}</h2>}>
          <QuoteLines quote={quote} />
        </Card>
        <InternalBlock quote={quote} />
        <DecisionCenter legacyTab="approve" legacySheet="approve" label={t("panel.sheetLabel")}>
          <ApprovalPanel quoteRef={refKey} />
        </DecisionCenter>
        <RecordTab tab="facts">
          <Requisites quote={quote} />
        </RecordTab>
        {quote.steps.length > 0 ? (
          <RecordTab tab="route">
            <RouteTimeline
              label={t("card.route")}
              steps={quote.steps}
              stepTitle={(step) => t(`card.routeStep.${step.status}`, { label: step.label })}
              decisionTitle={() => null}
            />
          </RecordTab>
        ) : null}
        <ClientComments quote={quote} />
      </div>
    </PageFrame>
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
