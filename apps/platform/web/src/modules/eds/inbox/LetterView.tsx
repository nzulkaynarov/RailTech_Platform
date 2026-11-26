import { Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { PersonRefCell } from "../../PersonRefCell";
import { ApiError } from "../../../shared/api/errors";
import type { DictionaryItem, LetterCard } from "../../../shared/api/generated/model";
import { useGetLetter } from "../../../shared/api/generated/platform-bff";
import { localName, useLetterDictionary } from "../dictionaries";
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
import { RecordHistory, type RecordHistoryEntry } from "../../../shared/ui/RecordHistory";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { DecisionCenter } from "../decision/DecisionCenter";
import { RecordTab } from "../decision/RecordTab";
import { letterRef } from "./api";
import { useStateLabels } from "./labels";
import { ReplyCard } from "../tasks/ReplyBlock";
import { InstructionsCard, OfficeDecision } from "./Instructions";
import { ClosedBanner } from "../tasks/LetterOutcomes";
import { DuplicateBanner, MarkDuplicateAction } from "./MarkDuplicate";
import { Attachments, RequestAttachments } from "./Parts";
import { ResolutionPanel } from "./ResolutionPanel";
import { PageFrame } from "../../../shared/ui/PageFrame";

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

/** «История» письма: журнал один — его печатает общая лента `RecordHistory`. */
function useJournalEntries(letter: LetterCard): RecordHistoryEntry[] {
  const { t } = useTranslation("letters");
  return letter.journal.map((entry) => ({
    at: entry.at,
    by: entry.by ? entry.by.name : null,
    action: t(`card.actions.${entry.action.replace(".", "_")}`, {
      defaultValue: t("card.actionUnknown"),
    }),
    comment: entry.comment ?? null,
  }));
}

/** Реквизиты делопроизводства (P8, SPEC-v3 §3.2a п. 1): вид, способ получения, подписал, срок по документу, связь. */
function useRegistryItems(letter: LetterCard) {
  const { t, i18n } = useTranslation("letters");
  const { date } = useFormat();
  // Справочники — со скрытыми значениями (EDS-REG): у старого письма вид или способ мог быть скрыт администратором.
  const kinds = useLetterDictionary("letter-kinds", true, Boolean(letter.kind));
  const methods = useLetterDictionary("receipt-methods", true, Boolean(letter.receipt_method));
  if (!letter.kind && !letter.receipt_method) return [];
  const label = (items: DictionaryItem[] | undefined, code: string | null | undefined) => {
    if (!code) return null;
    const found = items?.find((item) => item.code === code);
    return found ? localName(found.name, i18n.language) : code;
  };
  return [
    { label: t("card.fields.kind"), value: label(kinds.data?.items, letter.kind) },
    {
      label: t("card.fields.receiptMethod"),
      value: label(methods.data?.items, letter.receipt_method),
    },
    { label: t("card.fields.signedBy"), value: letter.signed_by },
    {
      label: t("card.fields.documentDue"),
      value: letter.document_due ? date(letter.document_due) : null,
    },
    {
      label: t("card.fields.related"),
      value: letter.related ? (
        <Link className="pf-focusable" to={letter.related.path}>
          {letter.related.number}
        </Link>
      ) : null,
    },
  ];
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
  const canResolve = canEdit(me, "eds.inbox");
  // Делопроизводитель готовит проект резолюции письма делопроизводства (P8b) в том же блоке решения.
  const office = letter.track === "office";
  const canRegister = canEdit(me, "eds.inbox.register");
  const registry = useRegistryItems(letter);
  const history = useJournalEntries(letter);
  // СЦ-11: письмо не по сделке — без строк заявки и клиента (там нечего показывать, кроме «—» и «не определён»)
  const withDeal = Boolean(letter.request || letter.client);

  return (
    <PageFrame layout="object">
      <div className="pf-letters pf-overlay-aware">
        <PageHeader
          title={t("card.title", { number: letter.number })}
          subtitle={letter.subject}
          extra={
            <div className="pf-fp-row">
              {letter.urgent ? <StatusTag tone="red">{t("card.urgent")}</StatusTag> : null}
              <StatusTag kind="incoming" status={letter.status} />
              {letter.on_control ? <StatusTag tone="blue">{t("card.onControl")}</StatusTag> : null}
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
        <DuplicateBanner letter={letter} />
        <ClosedBanner letter={letter} />
        {/* Путь заявки (7 шагов) — только у письма по заявке клиента; у делопроизводства своих шагов нет (P8b). */}
        {letter.track === "office" ? null : (
          <section className="pf-card pf-letters-steps" aria-label={t("card.steps")}>
            <RequestSteps
              stage={letter.stage}
              {...(letter.lost_at_step ? { step: letter.lost_at_step } : {})}
              {...(letter.request ? { number: letter.request.number } : {})}
            />
          </section>
        )}
        {/* EDS-DUP: «Это дубль ВХ-…» — у делопроизводителя */}
        {canRegister && letter.status !== "duplicate" ? (
          <div>
            <MarkDuplicateAction letter={letter} />
          </div>
        ) : null}
        <Card size="small" title={<h2 className="pf-letters-title">{t("card.summary")}</h2>}>
          <p className="pf-letters-summary">{letter.summary}</p>
        </Card>
        <Card size="small" title={<h2 className="pf-letters-title">{t("card.files")}</h2>}>
          {letter.files.length > 0 ? <Attachments files={letter.files} /> : null}
          {letter.request?.files?.length ? (
            <RequestAttachments
              letterId={letter.id}
              number={letter.request.number}
              files={letter.request.files}
            />
          ) : null}
          {letter.files.length === 0 && !letter.request?.files?.length ? (
            <p className="pf-hint">{t("card.noFiles")}</p>
          ) : null}
        </Card>
        <DecisionCenter
          legacyTab="resolution"
          legacySheet="resolution"
          label={t("panel.sheetLabel")}
        >
          <ResolutionPanel letterRef={refKey} />
        </DecisionCenter>
        <Decision letter={letter} />
        <OfficeDecision letter={letter} />
        <InstructionsCard letter={letter} />
        <ReplyCard letter={letter} />
        <RecordTab tab="facts">
          <DefinitionList
            items={[
              // СЦ-5: номер до перенумерации на латиницу — одна строка, только если он был
              ...(letter.previous_number
                ? [{ label: t("card.fields.previousNumber"), value: letter.previous_number }]
                : []),
              ...registry,
              // Делопроизводство (ГОСТ Р 7.0.97, SPEC-v3 §3.2a) — «корреспондент», заявка клиента — «клиент». Клиент CRM,
              // найденный по письму, — та же строка со ссылкой на карточку, а не вторая «Клиент».
              ...(letter.client
                ? [
                    {
                      label: t("card.linkFields.client"),
                      value: (
                        <>
                          <Link className="pf-focusable" to={letter.client.path}>
                            {letter.client.name ?? letter.client.id}
                          </Link>
                          {letter.client.inn ? (
                            <div className="pf-hint">
                              {t("card.byClient", { inn: letter.client.inn })}
                            </div>
                          ) : null}
                        </>
                      ),
                    },
                  ]
                : [
                    {
                      label: t(office ? "card.fields.correspondent" : "card.fields.client"),
                      value: letter.sender.name,
                    },
                    {
                      label: t(office ? "card.fields.correspondentInn" : "card.fields.inn"),
                      value: letter.sender.inn,
                    },
                  ]),
              ...(withDeal
                ? [
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
                  ]
                : []),
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
              { label: t("card.linkFields.manager"), value: letter.manager?.name },
              {
                label: t("card.linkFields.registered"),
                value: (
                  <span className="pf-instr-people">
                    <span>{date(letter.registered_at, "datetime")}</span>
                    {letter.registered_by ? (
                      <PersonRefCell person={letter.registered_by} caption={null} />
                    ) : (
                      <span className="pf-hint">{t("card.bySystem")}</span>
                    )}
                  </span>
                ),
              },
            ]}
          />
        </RecordTab>
        {history.length > 0 ? (
          <RecordTab tab="history">
            <RecordHistory label={t("card.journal")} entries={history} />
          </RecordTab>
        ) : null}
      </div>
    </PageFrame>
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
