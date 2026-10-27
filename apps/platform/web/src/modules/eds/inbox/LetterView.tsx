import { Button, Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { LetterCard } from "../../../shared/api/generated/model";
import { useGetLetter } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { LockIcon } from "../../../shared/ui/icons";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { RequestSteps } from "../../../shared/ui/RequestSteps";
import { SourceBanner } from "../../../shared/ui/SourceBanner";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { letterRef } from "./api";
import { useStateLabels } from "./labels";
import { Attachments } from "./Parts";
import { ResolutionSlot } from "./ResolutionPanel";

function Decision({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const res = letter.resolution;
  const items =
    letter.status === "resolved" && res
      ? [
          { label: t("card.decisionFields.text"), value: res.text },
          {
            label: t("card.decisionFields.assignees"),
            value: (
              <ul className="pf-res-assignees">
                {res.assignees.map((a) => (
                  <li key={`${a.zone}-${a.person.id}`}>
                    {a.person.name}{" "}
                    <span className="pf-hint">· {t(`form.zones.${a.zone}.name`)}</span>
                  </li>
                ))}
              </ul>
            ),
          },
          { label: t("card.decisionFields.due"), value: date(res.due) },
          ...(res.min_margin_pct !== undefined && res.min_margin_pct !== null
            ? [{ label: t("card.decisionFields.margin"), value: `${res.min_margin_pct} %` }]
            : []),
          {
            label: t("card.decisionFields.decidedBy"),
            value: `${res.decided_by.name} · ${date(res.decided_at, "datetime")}`,
          },
        ]
      : letter.status === "returned"
        ? [{ label: t("card.decisionFields.comment"), value: letter.return_comment }]
        : letter.status === "rejected"
          ? [{ label: t("card.decisionFields.reason"), value: letter.reject_reason }]
          : null;
  if (!items) return null;
  return (
    <Card size="small" title={<h2 className="pf-letters-title">{t("card.decision")}</h2>}>
      <DefinitionList items={items} />
    </Card>
  );
}

function Journal({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  if (letter.journal.length === 0) return null;
  return (
    <Card size="small" title={<h2 className="pf-letters-title">{t("card.journal")}</h2>}>
      <ol className="pf-letters-journal">
        {letter.journal.map((entry, index) => (
          <li key={`${entry.at}-${String(index)}`}>
            <strong>
              {t(`card.actions.${entry.action.replace(".", "_")}`, { defaultValue: entry.action })}
            </strong>
            <span className="pf-hint">
              {" "}
              · {entry.by ? entry.by.name : t("card.journalSystem")} · {date(entry.at, "datetime")}
            </span>
            {entry.comment ? <p className="pf-letters-note">{entry.comment}</p> : null}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function Links({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  return (
    <Card size="small" title={<h2 className="pf-letters-title">{t("card.links")}</h2>}>
      <DefinitionList
        items={[
          {
            label: t("card.linkFields.request"),
            value: letter.request ? (
              <>
                <Link className="pf-focusable" to={letter.request.path}>
                  {letter.request.number}
                </Link>
                {letter.request.title ? (
                  <div className="pf-hint">{letter.request.title}</div>
                ) : null}
              </>
            ) : (
              <span className="pf-hint">{t("card.noRequest")}</span>
            ),
          },
          {
            label: t("card.linkFields.client"),
            value: letter.client ? (
              <>
                <Link className="pf-focusable" to={letter.client.path}>
                  {letter.client.name ?? letter.client.id}
                </Link>
                {letter.client.inn ? (
                  <div className="pf-hint">{t("card.byClient", { inn: letter.client.inn })}</div>
                ) : null}
              </>
            ) : (
              <span className="pf-hint">{t("card.noClient")}</span>
            ),
          },
          { label: t("card.linkFields.manager"), value: letter.manager?.name },
          {
            label: t("card.linkFields.registered"),
            value: `${date(letter.registered_at, "datetime")} · ${
              letter.registered_by ? letter.registered_by.name : t("card.bySystem")
            }`,
          },
        ]}
      />
    </Card>
  );
}

function Content({
  letter,
  refKey,
  refetch,
}: {
  letter: LetterCard;
  refKey: string;
  refetch: () => void;
}) {
  const { t } = useTranslation("letters");
  const { me } = useAuth();
  const { date } = useFormat();
  const { wide, mobile } = useViewport();
  const [, setParams] = useSearchParams();
  const canResolve = canEdit(me, "eds.inbox");
  const awaiting = letter.status === "awaiting_resolution";

  const openResolution = () => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        // Телефон — лист на весь экран, планшет — окно справа (Drawer каркаса).
        if (mobile) next.set("sheet", "resolution");
        else next.set("panel", "open");
        next.set("tab", "resolution");
        return next;
      },
      { replace: true },
    );
  };

  return (
    <div className="pf-letters">
      <PageHeader
        title={t("card.title", { number: letter.number })}
        subtitle={letter.subject}
        extra={
          <div className="pf-fp-row">
            {letter.urgent ? <StatusTag tone="red">{t("card.urgent")}</StatusTag> : null}
            <StatusTag kind="incoming" status={letter.status} />
            {canResolve ? null : (
              <StatusTag tone="default">
                <span className="pf-letters-lock">
                  <LockIcon size={12} />
                  {t("card.readOnly")}
                </span>
              </StatusTag>
            )}
          </div>
        }
      />
      <SourceBanner sources={letter.sources} onRetry={refetch} />
      <section className="pf-card pf-letters-steps" aria-label={t("card.steps")}>
        <RequestSteps
          stage={letter.stage}
          {...(letter.lost_at_step ? { step: letter.lost_at_step } : {})}
          {...(letter.request ? { number: letter.request.number } : {})}
        />
      </section>
      {awaiting && canResolve && !wide ? (
        <div>
          <Button type="primary" onClick={openResolution}>
            {t("card.resolve")}
          </Button>
        </div>
      ) : null}
      {awaiting && !canResolve ? <p className="pf-hint">{t("card.readOnlyHint")}</p> : null}
      <div className="pf-letters-grid">
        <div className="pf-letters-main">
          <Card size="small" title={<h2 className="pf-letters-title">{t("card.details")}</h2>}>
            <DefinitionList
              items={[
                { label: t("card.fields.client"), value: letter.sender.name },
                { label: t("card.fields.inn"), value: letter.sender.inn },
                { label: t("card.fields.contact"), value: letter.sender.contact },
                {
                  label: t("card.fields.senderRef"),
                  value: [
                    letter.sender_ref.number,
                    letter.sender_ref.date ? date(letter.sender_ref.date) : null,
                  ]
                    .filter(Boolean)
                    .join(" · "),
                },
                { label: t("card.fields.addressee"), value: letter.addressee.name },
                { label: t("card.fields.received"), value: date(letter.received_at) },
                {
                  label: t("card.fields.urgency"),
                  value: letter.urgent ? t("card.urgent") : t("card.regular"),
                },
              ]}
            />
          </Card>
          <Card size="small" title={<h2 className="pf-letters-title">{t("card.summary")}</h2>}>
            <p className="pf-letters-summary">{letter.summary}</p>
          </Card>
          <Card size="small" title={<h2 className="pf-letters-title">{t("card.files")}</h2>}>
            {letter.files.length > 0 ? (
              <Attachments files={letter.files} />
            ) : (
              <p className="pf-hint">{t("card.noFiles")}</p>
            )}
          </Card>
          <Decision letter={letter} />
          <Journal letter={letter} />
        </div>
        <aside className="pf-letters-side" aria-label={t("card.links")}>
          <Links letter={letter} />
        </aside>
      </div>
      <ResolutionSlot letterRef={refKey} />
    </div>
  );
}

/** Карточка входящего письма (SPEC-v3 §7.3): шкала 7 шагов, реквизиты, суть, вложения, связи; «Резолюция» — в боковом окне. */
export function LetterView({ objectId }: { objectId: string }) {
  const { t } = useTranslation("letters");
  const query = useGetLetter(letterRef(objectId));
  const labels = useStateLabels();
  useDocumentTitle(t("card.title", { number: query.data?.number ?? objectId }));

  const error = query.error;
  if (error instanceof ApiError && error.status === 404) {
    return (
      <EmptyState
        title={t("state.notFound.title")}
        text={t("state.notFound.text")}
        action={<LinkButton to="/eds/inbox">{t("state.notFound.action")}</LinkButton>}
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
      <div className="pf-letters">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    );
  }
  return (
    <QueryState query={query} labels={labels}>
      {(letter) => (
        <Content
          letter={letter}
          refKey={objectId}
          refetch={() => {
            void query.refetch();
          }}
        />
      )}
    </QueryState>
  );
}
