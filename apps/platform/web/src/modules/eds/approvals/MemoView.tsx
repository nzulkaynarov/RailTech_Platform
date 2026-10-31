import { Button, Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { EdsRouteStep, MemoApprovalCard } from "../../../shared/api/generated/model";
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
import { History, type HistoryItem } from "../../../shared/ui/History";
import { LockIcon } from "../../../shared/ui/icons";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { DocumentStatusTag } from "../documents/status";
import { AgreeSlot } from "./AgreePanel";
import { memoRef } from "./api";
import { useStateLabels } from "./labels";
import { mayDecideMemos } from "./model";

function stepState(status: EdsRouteStep["status"]): HistoryItem["state"] {
  if (status === "current") return "waiting";
  if (status === "pending") return "todo";
  return "done";
}

function Route({ memo }: { memo: MemoApprovalCard }) {
  const { t } = useTranslation("approvals");
  const { date } = useFormat();
  const items: HistoryItem[] = [
    {
      state: "done",
      title: t("card.routeAuthor", { name: memo.author.full_name }),
      meta: date(memo.created_at, "datetime"),
    },
    ...memo.steps.map((step) => ({
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
    })),
  ];
  return <History items={items} label={t("card.route")} />;
}

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

function Decisions({ memo }: { memo: MemoApprovalCard }) {
  const { t } = useTranslation("approvals");
  const { date } = useFormat();
  if (memo.decisions.length === 0) return null;
  return (
    <Card size="small" title={<h2 className="pf-dec-title">{t("card.decisions")}</h2>}>
      <ol className="pf-dec-list" aria-label={t("card.decisions")}>
        {memo.decisions.map((d, index) => (
          <li key={`${d.at}-${String(index)}`}>
            <strong>{t(`card.decision.${d.decision}`)}</strong>
            <span className="pf-hint">
              {" "}
              · {d.by.full_name} · {date(d.at, "datetime")}
            </span>
            {d.comment ? <p className="pf-dec-note">{d.comment}</p> : null}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function Content({ memo, refKey }: { memo: MemoApprovalCard; refKey: string }) {
  const { t } = useTranslation("approvals");
  const { me } = useAuth();
  const { date } = useFormat();
  const { wide, mobile } = useViewport();
  const [, setParams] = useSearchParams();
  const mayDecide = mayDecideMemos(me);
  const waiting = memo.status === "open" && memo.can_decide && mayDecide;
  const number = memo.number ?? t(`kinds.${memo.kind}`);

  const openAgree = () => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (mobile) next.set("sheet", "agree");
        else next.set("panel", "open");
        next.set("tab", "agree");
        return next;
      },
      { replace: true },
    );
  };

  return (
    <div className="pf-dec-page">
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
      {waiting && !wide ? (
        <div>
          <Button type="primary" onClick={openAgree}>
            {t("card.agree")}
          </Button>
        </div>
      ) : null}
      {memo.status === "open" && !waiting ? (
        <p className="pf-hint">{t("card.readOnlyHint")}</p>
      ) : null}
      <div className="pf-dec-grid">
        <div className="pf-dec-main">
          <Card size="small" title={<h2 className="pf-dec-title">{t("card.text")}</h2>}>
            <p className="pf-dec-text">{memo.text}</p>
          </Card>
          <Card size="small" title={<h2 className="pf-dec-title">{t("card.files")}</h2>}>
            <Files memo={memo} />
          </Card>
          <Card size="small" title={<h2 className="pf-dec-title">{t("card.route")}</h2>}>
            <Route memo={memo} />
          </Card>
          <Decisions memo={memo} />
        </div>
        <aside className="pf-dec-side" aria-label={t("card.requisites")}>
          <Card size="small" title={<h2 className="pf-dec-title">{t("card.requisites")}</h2>}>
            <DefinitionList
              items={[
                { label: t("card.fields.kind"), value: t(`kinds.${memo.kind}`) },
                { label: t("card.fields.from"), value: memo.author.full_name },
                {
                  label: t("card.fields.to"),
                  value: memo.addressee ? memo.addressee.full_name : t("card.toDirector"),
                },
                { label: t("card.fields.date"), value: date(memo.created_at, "datetime") },
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
          </Card>
        </aside>
      </div>
      <AgreeSlot memoRef={refKey} />
    </div>
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
