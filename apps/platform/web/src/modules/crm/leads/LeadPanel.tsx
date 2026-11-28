import { Button, Skeleton, Tag } from "antd";
import { useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { ClientInvitation, LeadCard, LeadNotice } from "../../../shared/api/generated/model";
import { useGetCrmLead, useReopenCrmLead } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { DoNotWorkStrip } from "../../../shared/ui/DoNotWorkStrip";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { LongText } from "../../../shared/ui/LongText";
import { CloseMenu } from "../messages/CloseMenu";
import { HandOverButton } from "../messages/HandOver";
import { useRefreshMessages } from "../messages/actions";
import { actionError, channelLabel, factRows } from "../messages/labels";
import { canCreateFromLead } from "../common/access";
import { leadActionRules } from "../common/leadActions";
import { ContactsBlock } from "./ContactsBlock";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { TestTag } from "../../../shared/ui/TestTag";
import { calcPath } from "../../erp/calc/api";
import { clientPath } from "../common/params";

import "../crm.css";

type Format = ReturnType<typeof useFormat>;

/** «Откуда» одной строкой: канал словами, форма, страница, кампания (LID-5); без фактов — только канал. */
function originText(t: TFunction, card: LeadCard): string {
  const parts = [channelLabel(t, card.channel)];
  const origin = card.origin;
  if (origin) {
    if (origin.form) {
      parts.push(t(`leads:origin.forms.${origin.form}`, { defaultValue: origin.form }));
    }
    if (origin.page) parts.push(origin.page);
    if (origin.campaign) parts.push(t("leads:origin.campaign", { name: origin.campaign }));
  }
  return parts.join(" · ");
}

/** Канал приглашения словами: известные — «Почта», «Telegram», «Почта и Telegram»; незнакомое значение — «другой канал»,
 * сырой код («both», «none») в интерфейс не попадает (КЛИЕНТ-1). */
function noticeChannelWord(t: TFunction, channel: string): string {
  return ["email", "telegram", "both"].includes(channel)
    ? t(`clients:card.resendChannels.${channel}`)
    : channelLabel(t, channel);
}

/** «Заявка RQ-… создана» — по номеру ERP; без номера — без выдумок: «Заявка создана» или «не передана в учёт». */
function requestMadeText(t: TFunction, request: NonNullable<LeadCard["request"]>): string {
  if (request.transfer === "failed") return t("leads:request.madeFailed");
  return request.number
    ? t("leads:request.made", { number: request.number })
    : t("leads:request.madeNoNumber");
}

/** Итог уведомления клиенту (подтверждение заявки, приглашение) одной строкой: статус, канал, причина отказа. */
function noticeText(t: TFunction, fmt: Format, notice: LeadNotice | ClientInvitation): string {
  const parts = [
    notice.status === "sent"
      ? t("leads:card.notice.sent", {
          date: notice.sent_at ? fmt.date(notice.sent_at, "datetime") : "",
        })
      : notice.status === "failed"
        ? t("leads:card.notice.failed", { reason: notice.error_text ?? t("leads:card.none") })
        : t(`leads:card.notice.${notice.status}`),
  ];
  if (notice.channel) {
    parts.push(t("leads:card.notice.channel", { channel: noticeChannelWord(t, notice.channel) }));
  }
  return parts.join(" · ");
}

function consentText(t: TFunction, fmt: Format, card: LeadCard): string {
  const { given_at: at, method } = card.consent;
  if (!at) {
    return t(
      card.channel === "telegram" ? "leads:card.consentMissingBot" : "leads:card.consentMissing",
    );
  }
  if (method === null && card.channel === "web") {
    return t("leads:card.consentForm", { date: fmt.date(at) });
  }
  if (method === null) return t("leads:card.consentBot", { date: fmt.date(at) });
  return t("leads:card.consentStaff", {
    date: fmt.date(at),
    method: t(`leads:card.methods.${method}`),
  });
}

/** Запрос лида — тот же текст, что уже есть в его сообщениях (письмо: запрос = тело письма). */
function repeatsMessage(need: string, messages: readonly { text: string }[]): boolean {
  const squash = (value: string) => value.replace(/\s+/g, " ").trim();
  const wanted = squash(need);
  return wanted.length > 0 && messages.some((message) => squash(message.text).includes(wanted));
}

function Body({ card, sheet, onClose }: { card: LeadCard; sheet: boolean; onClose: () => void }) {
  const { t } = useTranslation(["leads", "messages", "clients"]);
  const fmt = useFormat();
  const { me } = useAuth();
  const canCreate = canCreateFromLead(me, card.assigned) && card.status !== "lost";
  const rules = leadActionRules(me, card.assigned, card.status);
  const refresh = useRefreshMessages();
  const [reopenFailure, setReopenFailure] = useState<string | null>(null);
  const reopen = useReopenCrmLead({
    mutation: {
      onSuccess: () => {
        setReopenFailure(null);
        refresh();
      },
      onError: (error) => {
        setReopenFailure(actionError(t, error));
      },
    },
  });
  // Первая линия (D17G-1): «Передать менеджеру» вместо «Забрать» и ответа — пока лида не ведёт сотрудник
  // (свободен или передан, но не забран).
  const triage = !canEdit(me, "crm.leads") && canEdit(me, "crm.leads.triage");
  const handable =
    triage && (!card.assigned || Boolean(card.handoff?.reasons.includes("handed_over")));
  // CH-1: отвечать некуда — вместо «Ответить» «Позвонить» (только телефон) или «Открыть переписку».
  const noChannel = card.reply_via === null;
  const callOnly = noChannel ? card.contacts.phone : null;
  const facts = factRows(t, card.facts);
  // Запрос из письма уже напечатан сообщением ниже: второй раз целиком не показываем (СЦ-7, N5)
  const need = card.need && !repeatsMessage(card.need, card.last_messages) ? card.need : null;
  return (
    <div className="pf-fp-stack">
      <div className="pf-fp-stack" style={{ gap: 4 }}>
        <h3 className="pf-fp-title">{card.name}</h3>
        <div className="pf-fp-row" style={{ alignItems: "center" }}>
          <span className="pf-hint">{card.lead}</span>
          <TestTag value={card.is_test} />
          {card.partner_application != null ? (
            <Tag>{t("leads:card.partner")}</Tag>
          ) : (
            <StatusTag kind="lead" status={card.status} />
          )}
          {card.discarded ? (
            <span className="pf-hint">
              {t(`leads:discarded.${card.discarded}`)}
              {card.duplicate_of ? (
                <>
                  {" · "}
                  <LinkButton
                    type="link"
                    size="small"
                    style={{ padding: 0 }}
                    to={`/crm/leads?lead=${card.duplicate_of}&panel=open`}
                  >
                    {card.duplicate_of}
                  </LinkButton>
                </>
              ) : null}
            </span>
          ) : null}
        </div>
      </div>

      <DoNotWorkStrip mark={card.client?.do_not_work} />

      <ContactsBlock key={card.lead} card={card} canEdit={rules.edit} />

      <div className="pf-fp-block">
        <h4>{t("leads:card.about")}</h4>
        <DefinitionList
          items={[
            { label: t("leads:card.channel"), value: originText(t, card) },
            {
              label: t("leads:card.language"),
              value: t(`messages:card.languages.${card.language}`),
            },
            { label: t("leads:card.assigned"), value: card.assigned?.name ?? t("leads:nobody") },
            { label: t("leads:card.consent"), value: consentText(t, fmt, card) },
            {
              label: t("leads:card.client"),
              value: card.client ? (
                <LinkButton
                  type="link"
                  size="small"
                  style={{
                    padding: 0,
                    height: "auto",
                    whiteSpace: "normal",
                    textAlign: "left",
                    overflowWrap: "anywhere",
                  }}
                  to={clientPath(card.client.id)}
                >
                  {card.client.name}
                </LinkButton>
              ) : null,
            },
            ...(card.request && card.client
              ? [
                  {
                    label: t("leads:card.request"),
                    value: (
                      <span data-testid="lead-request">
                        {requestMadeText(t, card.request)}{" "}
                        {card.request.number ? (
                          <LinkButton
                            type="link"
                            size="small"
                            style={{ padding: 0 }}
                            to={calcPath(card.request.number)}
                          >
                            {t("leads:actions.openRequest")}
                          </LinkButton>
                        ) : (
                          <LinkButton
                            type="link"
                            size="small"
                            style={{ padding: 0 }}
                            to={clientPath(card.client.id)}
                          >
                            {t("leads:actions.openClient")}
                          </LinkButton>
                        )}
                      </span>
                    ),
                  },
                ]
              : []),
            ...(card.partner_application != null
              ? [
                  {
                    label: t("leads:card.partnerOpen"),
                    value: canEdit(me, "erp.stock") ? (
                      <LinkButton
                        type="link"
                        size="small"
                        style={{ padding: 0 }}
                        to="/crm/clients?kind=applications"
                      >
                        {`№ ${String(card.partner_application)}`}
                      </LinkButton>
                    ) : (
                      `№ ${String(card.partner_application)}`
                    ),
                  },
                ]
              : []),
            ...(card.first_response.due_at
              ? [
                  {
                    label: t("leads:card.firstResponse"),
                    value: card.first_response.overdue
                      ? t("leads:card.firstResponseOverdue", {
                          date: fmt.date(card.first_response.due_at, "datetime"),
                        })
                      : t("leads:card.firstResponseDue", {
                          date: fmt.date(card.first_response.due_at, "datetime"),
                        }),
                  },
                ]
              : []),
            ...(card.confirmation
              ? [
                  {
                    label: t("leads:card.confirmation"),
                    value: noticeText(t, fmt, card.confirmation),
                  },
                ]
              : []),
            ...(card.invitation
              ? [{ label: t("leads:card.invitation"), value: noticeText(t, fmt, card.invitation) }]
              : []),
          ]}
        />
      </div>

      {need || facts.length > 0 || !card.need ? (
        <div className="pf-fp-block">
          <h4>{t(card.channel === "telegram" ? "leads:card.facts" : "leads:card.factsOther")}</h4>
          {need ? (
            <DefinitionList
              items={[{ label: t("leads:card.need"), value: <LongText text={need} /> }]}
            />
          ) : null}
          {facts.length ? (
            <DefinitionList items={facts} />
          ) : need ? null : (
            <p className="pf-fp-sub">{t("leads:card.none")}</p>
          )}
        </div>
      ) : null}

      <div className="pf-fp-block">
        <h4>{t("leads:card.messages")}</h4>
        {card.last_messages.length ? (
          <ol className="pf-crm-messages" aria-label={t("leads:card.messages")}>
            {card.last_messages.map((message, index) => (
              <li key={index} className="pf-crm-message" data-author={message.author}>
                <span className="pf-hint">
                  {t(`leads:card.authors.${message.author}`)} · {fmt.date(message.at, "datetime")}
                </span>
                <LongText className="pf-crm-message-text" text={message.text} />
              </li>
            ))}
          </ol>
        ) : (
          <p className="pf-fp-sub">{t("leads:card.noMessages")}</p>
        )}
      </div>

      <div className="pf-crm-actions" data-sheet={sheet}>
        {canCreate ? (
          <LinkButton
            {...(card.request ? {} : { type: "primary" as const })}
            to={`/crm/leads?lead=${card.lead}&create=1&panel=open&tab=card`}
          >
            {t(card.request ? "leads:actions.another" : "leads:actions.create")}
          </LinkButton>
        ) : null}
        {handable ? <HandOverButton lead={card.lead} name={card.name} /> : null}
        {callOnly ? (
          <Button href={`tel:${callOnly.replace(/[^\d+]/g, "")}`}>{t("leads:actions.call")}</Button>
        ) : null}
        <LinkButton to={`/crm/leads?scope=waiting&lead=${card.lead}`}>
          {t(triage || noChannel || callOnly ? "leads:actions.openChat" : "leads:actions.reply")}
        </LinkButton>
        {rules.reopen ? (
          <Button
            loading={reopen.isPending}
            onClick={() => {
              reopen.mutate({ lead: card.lead });
            }}
          >
            {t("leads:actions.reopen")}
          </Button>
        ) : null}
        <CloseMenu
          lead={card.lead}
          name={card.name}
          close={rules.close}
          discard={rules.discard}
          inline
        />
        {sheet ? <Button onClick={onClose}>{t("leads:card.close")}</Button> : null}
      </div>
      <ErrorNote message={reopenFailure} />
    </div>
  );
}

/**
 * Карточка лида в боковом окне (SPEC-v3 §7.2): контакты и каналы, согласие на данные, факты квалификации от бота, последние
 * сообщения, срок первого ответа и итог подтверждения заявки клиенту (D1-9). Отсюда — «Создать заявку» и «Ответить»; у
 * первой линии (D17G-1) — «Передать менеджеру» и «Открыть переписку».
 */
export function LeadPanel({ lead, onClose }: { lead: string; onClose: () => void }) {
  const { t } = useTranslation("leads");
  const { mobile } = useViewport();
  const query = useGetCrmLead(lead);
  if (query.isPending) return <Skeleton active paragraph={{ rows: 6 }} title={false} />;
  if (query.isError) {
    const status = query.error instanceof ApiError ? query.error.status : 0;
    return (
      <EmptyState
        level={3}
        compact
        title={t(status === 404 ? "empty.filteredTitle" : "loadError.title")}
        text={t(status === 404 ? "empty.filteredText" : "loadError.text")}
        action={
          status === 404 ? undefined : (
            <Button
              onClick={() => {
                void query.refetch();
              }}
            >
              {t("retry")}
            </Button>
          )
        }
      />
    );
  }
  return <Body card={query.data} sheet={mobile} onClose={onClose} />;
}
