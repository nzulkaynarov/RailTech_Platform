import { Alert, Button, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import { downloadFile } from "../../../shared/api/download";
import type { EdsDocument } from "../../../shared/api/generated/model";
import {
  getDownloadEdsDocumentFileUrl,
  useGetEdsDocument,
} from "../../../shared/api/generated/platform-bff";
import { formatFileSize } from "../../../shared/lib/fileSize";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { DocNumber } from "../../../shared/ui/DocNumber";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { History, type HistoryItem } from "../../../shared/ui/History";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { reasonText } from "./errors";
import { DocumentStatusTag } from "./status";

import "./documents.css";

type Step = EdsDocument["route"][number];

function stepState(status: Step["status"]): HistoryItem["state"] {
  if (status === "current") return "waiting";
  if (status === "pending") return "todo";
  return "done";
}

function Files({ doc }: { doc: EdsDocument }) {
  const { t, i18n } = useTranslation("documents");
  const [error, setError] = useState<string | null>(null);
  if (doc.files.length === 0) return <p className="pf-fp-sub">{t("panel.noFiles")}</p>;
  return (
    <>
      <ul className="pf-doc-files" aria-label={t("panel.files")}>
        {doc.files.map((file) => (
          <li key={file.id} className="pf-doc-file">
            <Button
              type="link"
              size="small"
              style={{ padding: 0, height: "auto", whiteSpace: "normal", textAlign: "left" }}
              aria-label={t("panel.download", { name: file.name })}
              onClick={() => {
                setError(null);
                downloadFile(getDownloadEdsDocumentFileUrl(file.id), file.name).catch(
                  (failure: unknown) => {
                    setError(t("panel.downloadFailed", { reason: reasonText(t, failure) }));
                  },
                );
              }}
            >
              <span className="pf-doc-file-name">{file.name}</span>
            </Button>
            <span className="pf-hint">{formatFileSize(file.size, i18n.language)}</span>
          </li>
        ))}
      </ul>
      {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
    </>
  );
}

function Route({ doc }: { doc: EdsDocument }) {
  const { t } = useTranslation("documents");
  const { date } = useFormat();
  if (doc.route.length === 0) {
    const accountant = doc.amount && doc.kind === "memo" ? t("panel.routePreviewAccountant") : "";
    return doc.kind === "letter_out" ? null : (
      <p className="pf-fp-sub">{t("panel.routePreview", { accountant })}</p>
    );
  }
  const items: HistoryItem[] = [
    {
      state: "done",
      title: t("panel.routeAuthor", { name: doc.author.full_name }),
      meta: t("panel.routeAuthorMeta", { date: date(doc.created_at, "datetime") }),
    },
    ...doc.route.map((step) => ({
      state: stepState(step.status),
      title: t(`panel.routeStep.${step.status}`, { label: step.label }),
      meta:
        step.decided_at && step.decided_by
          ? `${date(step.decided_at, "datetime")} · ${step.decided_by.full_name}`
          : undefined,
    })),
  ];
  return <History items={items} label={t("panel.route")} />;
}

function Decisions({ doc }: { doc: EdsDocument }) {
  const { t } = useTranslation("documents");
  const { date } = useFormat();
  if (doc.decisions.length === 0) return <p className="pf-fp-sub">{t("panel.noDecisions")}</p>;
  const items: HistoryItem[] = doc.decisions.map((decision) => ({
    state: "done",
    title: t(`panel.decision.${decision.decision}`),
    meta: (
      <>
        {t("panel.decisionMeta", {
          date: date(decision.at, "datetime"),
          name: decision.by.full_name,
          round: decision.round,
        })}
        {decision.comment ? <p className="pf-doc-comment">{decision.comment}</p> : null}
      </>
    ),
  }));
  return <History items={items} label={t("panel.decisions")} />;
}

function Details({ doc }: { doc: EdsDocument }) {
  const { t } = useTranslation("documents");
  const { date } = useFormat();
  const isLetter = doc.kind === "letter_out";
  return (
    <DefinitionList
      items={[
        { label: t("panel.fields.kind"), value: t(`kinds.${doc.kind}`) },
        { label: t("panel.fields.author"), value: doc.author.full_name },
        isLetter
          ? {
              label: t("panel.fields.recipient"),
              value: doc.recipient
                ? [doc.recipient.name, doc.recipient.inn].filter(Boolean).join(", ")
                : null,
            }
          : {
              label: t("panel.fields.addressee"),
              value: doc.addressee ? doc.addressee.full_name : t("panel.toDirector"),
            },
        {
          label: t("panel.fields.amount"),
          value: doc.amount ? (
            <MoneyText value={doc.amount.amount} currency={doc.amount.currency} />
          ) : null,
        },
        { label: t("panel.fields.due"), value: doc.due_date ? date(doc.due_date) : null },
        {
          label: t("panel.fields.deal"),
          value: doc.deal ? (doc.deal.number ?? String(doc.deal.erp_deal_id)) : null,
        },
        { label: t("panel.fields.created"), value: date(doc.created_at, "datetime") },
        { label: t("panel.fields.updated"), value: date(doc.updated_at, "datetime") },
        ...(doc.version > 1 ? [{ label: t("panel.fields.version"), value: doc.version }] : []),
      ]}
    />
  );
}

function Body({ doc, sheet, onClose }: { doc: EdsDocument; sheet: boolean; onClose: () => void }) {
  const { t } = useTranslation("documents");
  return (
    <div className="pf-fp-stack">
      <div className="pf-fp-stack" style={{ gap: 8 }}>
        <h3 className="pf-fp-title">{doc.subject}</h3>
        <div className="pf-fp-row" style={{ alignItems: "center" }}>
          {doc.number ? (
            <DocNumber number={doc.number} />
          ) : (
            <span className="pf-hint">{t("list.noNumber")}</span>
          )}
          <DocumentStatusTag kind={doc.kind} status={doc.status} />
        </div>
      </div>
      <Details doc={doc} />
      <div className="pf-fp-block">
        <h4>{t("panel.text")}</h4>
        <p className="pf-doc-text">{doc.text}</p>
      </div>
      <div className="pf-fp-block">
        <h4>{t("panel.files")}</h4>
        <Files doc={doc} />
      </div>
      <div className="pf-fp-block">
        <h4>{t("panel.route")}</h4>
        <Route doc={doc} />
      </div>
      <div className="pf-fp-block">
        <h4>{t("panel.decisions")}</h4>
        <Decisions doc={doc} />
      </div>
      <div className="pf-doc-actions" data-sheet={sheet}>
        {doc.can_edit ? (
          <LinkButton type="primary" to={`/eds/new?draft=${doc.id}`}>
            {t("panel.continue")}
          </LinkButton>
        ) : null}
        {sheet ? (
          <Button onClick={onClose} aria-label={t("panel.closeLabel")}>
            {t("panel.close")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/** Карточка документа: статус словами, реквизиты, текст, вложения, маршрут и решения с датой и автором (SPEC-v3 §2.4, §7.3). */
export function DocumentCard({
  id,
  sheet = false,
  onClose,
}: {
  id: string;
  /** Полноэкранный лист на мобильном: кнопки прижаты к низу */
  sheet?: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation("documents");
  const query = useGetEdsDocument(id);
  if (query.isPending) return <Skeleton active paragraph={{ rows: 6 }} title={false} />;
  if (query.isError) {
    const error = query.error;
    const status = error instanceof ApiError ? error.status : 0;
    const key = status === 404 ? "notFound" : status === 403 ? "forbidden" : "loadError";
    return (
      <EmptyState
        level={3}
        compact
        title={t(`panel.${key}.title`)}
        text={t(`panel.${key}.text`)}
        action={
          status === 403 || status === 404 ? undefined : (
            <Button
              onClick={() => {
                void query.refetch();
              }}
            >
              {t("panel.retry")}
            </Button>
          )
        }
      />
    );
  }
  return <Body doc={query.data} sheet={sheet} onClose={onClose} />;
}
