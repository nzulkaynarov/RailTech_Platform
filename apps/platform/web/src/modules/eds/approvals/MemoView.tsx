import { Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { MemoApprovalCard } from "../../../shared/api/generated/model";
import {
  getDownloadEdsDocumentFileUrl,
  useGetMemoApproval,
} from "../../../shared/api/generated/platform-bff";
import { formatFileSize } from "../../../shared/lib/fileSize";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { LockIcon } from "../../../shared/ui/icons";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { RouteTimeline } from "../../../shared/ui/RouteTimeline";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { DecisionCenter } from "../decision/DecisionCenter";
import { RecordTab } from "../decision/RecordTab";
import { DocumentStatusTag } from "../documents/status";
import { AgreePanel } from "./AgreePanel";
import { memoRef } from "./api";
import { useStateLabels } from "./labels";
import { mayDecideMemos } from "./model";
import { PageFrame } from "../../../shared/ui/PageFrame";

function Files({ memo }: { memo: MemoApprovalCard }) {
  const { t, i18n } = useTranslation("approvals");
  if (memo.files.length === 0) return <p className="pf-hint">{t("card.noFiles")}</p>;
  return (
    <ul className="pf-dec-list" aria-label={t("card.files")}>
      {memo.files.map((file) => (
        <li key={file.id}>
          <a
            className="pf-focusable pf-dec-link"
            href={getDownloadEdsDocumentFileUrl(file.id)}
            download
            aria-label={t("card.download", { name: file.name })}
          >
            {file.name}
          </a>
          <span className="pf-hint">{formatFileSize(file.size, i18n.language)}</span>
        </li>
      ))}
    </ul>
  );
}

function Content({ memo, refKey }: { memo: MemoApprovalCard; refKey: string }) {
  const { t } = useTranslation("approvals");
  const { me } = useAuth();
  const { date } = useFormat();
  const mayDecide = mayDecideMemos(me) || Boolean(memo.acting_for);
  const number = memo.number ?? t(`kinds.${memo.kind}`);

  return (
    <PageFrame layout="object">
      <div className="pf-dec-page pf-overlay-aware">
        <PageHeader
          title={t("card.title", { number })}
          subtitle={memo.subject}
          extra={
            <div className="pf-dec-row">
              <DocumentStatusTag kind="memo" status={memo.document_status} />
              {mayDecide && memo.can_decide ? null : (
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
        <Card size="small" title={<h2 className="pf-dec-title">{t("card.text")}</h2>}>
          <p className="pf-dec-text">{memo.text}</p>
        </Card>
        <Card size="small" title={<h2 className="pf-dec-title">{t("card.files")}</h2>}>
          <Files memo={memo} />
        </Card>
        <DecisionCenter legacyTab="agree" legacySheet="agree" label={t("panel.sheetLabel")}>
          <AgreePanel memoRef={refKey} />
        </DecisionCenter>
        <RecordTab tab="facts">
          <DefinitionList
            items={[
              { label: t("card.fields.kind"), value: t(`kinds.${memo.kind}`) },
              {
                label: t("card.fields.to"),
                value: memo.addressee ? memo.addressee.full_name : t("card.toDirector"),
              },
              {
                label: t("card.fields.amount"),
                value: memo.amount ? (
                  <MoneyText value={memo.amount.amount} currency={memo.amount.currency} />
                ) : null,
              },
              { label: t("card.fields.due"), value: memo.due_date ? date(memo.due_date) : null },
              {
                label: t("card.fields.deal"),
                value: memo.deal ? (memo.deal.number ?? String(memo.deal.erp_deal_id)) : null,
              },
            ]}
          />
        </RecordTab>
        <RecordTab tab="route">
          <RouteTimeline
            label={t("card.route")}
            steps={memo.steps}
            decisions={memo.decisions}
            author={{
              name: memo.author.full_name,
              at: memo.created_at,
              title: (name) => t("card.routeAuthor", { name }),
            }}
            stepTitle={(step) => t(`card.routeStep.${step.status}`, { label: step.label })}
            decisionTitle={(d) => t(`card.decision.${d.decision}`)}
          />
        </RecordTab>
      </div>
    </PageFrame>
  );
}

/** Карточка документа на согласовании (SPEC-v3 §7.3): реквизиты, текст, вложения, маршрут; «Согласование» — в боковом окне. */
export function MemoView({ objectId }: { objectId: string }) {
  const { t } = useTranslation("approvals");
  const query = useGetMemoApproval(memoRef(objectId));
  const labels = useStateLabels();
  useDocumentTitle(t("card.title", { number: query.data?.number ?? objectId }));

  const error = query.error;
  if (error instanceof ApiError && error.status === 404) {
    return (
      <EmptyState
        title={t("state.notFound.title")}
        text={t("state.notFound.text")}
        action={<LinkButton to="/eds/approvals">{t("state.notFound.action")}</LinkButton>}
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
      {(memo) => <Content memo={memo} refKey={objectId} />}
    </QueryState>
  );
}
