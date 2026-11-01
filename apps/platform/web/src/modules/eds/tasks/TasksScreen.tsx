import { Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { LetterCard } from "../../../shared/api/generated/model";
import { useGetLetter } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { letterPath, letterRef } from "../inbox/api";
import { InstructionsCard, OfficeDecision } from "../inbox/Instructions";
import { useStateLabels } from "../inbox/labels";
import { Attachments } from "../inbox/Parts";
import { AcquaintAction, MyInstruction } from "./TaskActions";

import "../inbox/inbox.css";
import "../new/new.css";

function Content({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const { me } = useAuth();
  const { date } = useFormat();
  const mine = (letter.instructions ?? []).find(
    (i) => i.person.id === me.id && i.status === "in_work",
  );
  const acquaint = (letter.acquaintances ?? []).find(
    (a) => a.person.id === me.id && !a.acknowledged_at,
  );
  const author = letter.office_resolution?.decided_by.id === me.id;
  const waitsAuthor =
    author &&
    (letter.instructions ?? []).some((i) => i.extensions.some((e) => e.status === "pending"));
  const canOpenCard = canSee(me, { anyOf: ["eds.inbox", "eds.inbox.register"] });
  return (
    <div className="pf-letters">
      <PageHeader
        title={t("tasks.title", { number: letter.number })}
        subtitle={letter.subject}
        extra={
          <div className="pf-fp-row">
            {letter.urgent ? <StatusTag tone="red">{t("card.urgent")}</StatusTag> : null}
            <StatusTag kind="incoming" status={letter.status} />
            {letter.on_control ? <StatusTag tone="blue">{t("card.onControl")}</StatusTag> : null}
          </div>
        }
      />
      <div className="pf-letters-grid">
        <div className="pf-letters-main">
          {mine ? <MyInstruction letter={letter} instruction={mine} /> : null}
          {acquaint ? <AcquaintAction letter={letter} /> : null}
          {!mine && !acquaint && !waitsAuthor ? (
            <EmptyState
              level={2}
              compact
              title={t("tasks.noTask.title")}
              text={t("tasks.noTask.text")}
            />
          ) : null}
          <InstructionsCard letter={letter} />
          <OfficeDecision letter={letter} />
        </div>
        <aside className="pf-letters-side" aria-label={t("tasks.letter")}>
          <Card size="small" title={<h2 className="pf-letters-title">{t("tasks.letter")}</h2>}>
            <DefinitionList
              items={[
                { label: t("card.fields.client"), value: letter.sender.name },
                { label: t("card.fields.received"), value: date(letter.received_at) },
                {
                  label: t("card.fields.documentDue"),
                  value: letter.document_due ? date(letter.document_due) : null,
                },
                { label: t("card.fields.addressee"), value: letter.addressee.name },
              ]}
            />
            <h3 className="pf-res-subhead">{t("card.summary")}</h3>
            <p className="pf-letters-summary">{letter.summary}</p>
            {letter.files.length > 0 ? (
              <>
                <h3 className="pf-res-subhead">{t("card.files")}</h3>
                <Attachments files={letter.files} />
              </>
            ) : null}
            {canOpenCard ? (
              <LinkButton size="small" to={letterPath(letter.number)}>
                {t("tasks.openCard")}
              </LinkButton>
            ) : null}
          </Card>
        </aside>
      </div>
    </div>
  );
}

/**
 * Рабочий экран поручения (P8b, SPEC-v3 §3.2a п. 3–4): «Мои задачи» → поручение, перенос срока или «Ознакомиться».
 * Исполнитель видит письмо своего поручения даже без раздела «Входящие» — карточку отдаёт BFF (решает EDS).
 */
export function TasksScreen({ objectId }: { objectId?: string | undefined }) {
  const { t } = useTranslation("letters");
  const query = useGetLetter(letterRef(objectId ?? ""), {
    query: { enabled: Boolean(objectId) },
  });
  const labels = useStateLabels();
  useDocumentTitle(t("tasks.title", { number: query.data?.number ?? objectId ?? "" }));
  if (!objectId) {
    return <EmptyState title={t("tasks.noTask.title")} text={t("tasks.noTask.text")} />;
  }
  const error = query.error;
  if (error instanceof ApiError && error.status === 404) {
    return <EmptyState title={t("state.notFound.title")} text={t("state.notFound.text")} />;
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
      {(letter) => <Content letter={letter} />}
    </QueryState>
  );
}
