import { Button, Skeleton } from "antd";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type { ClientInvitation, LeadCard, LeadNotice } from "../../../shared/api/generated/model";
import { useGetCrmLead } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { channelLabel, factRows } from "../messages/labels";
import { clientPath } from "../common/params";

import "../crm.css";

type Format = ReturnType<typeof useFormat>;

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
    const known = ["email", "telegram", "both"].includes(notice.channel);
    const channel = known
      ? t(`clients:card.resendChannels.${notice.channel}`)
      : channelLabel(t, notice.channel);
    parts.push(t("leads:card.notice.channel", { channel }));
  }
  return parts.join(" · ");
}

function consentText(t: TFunction, fmt: Format, card: LeadCard): string {
  const { given_at: at, method } = card.consent;
  if (!at) return t("leads:card.consentMissing");
  if (method === null) return t("leads:card.consentBot", { date: fmt.date(at) });
  return t("leads:card.consentStaff", {
    date: fmt.date(at),
    method: t(`leads:card.methods.${method}`),
  });
}

function Body({ card, sheet, onClose }: { card: LeadCard; sheet: boolean; onClose: () => void }) {
  const { t } = useTranslation(["leads", "messages", "clients"]);
  const fmt = useFormat();
  const { me } = useAuth();
  const canCreate = canEdit(me, "crm.clients") && card.status !== "lost";
  const contacts = [
    {
      label: t("messages:card.telegram"),
      value: card.contacts.telegram ? `@${card.contacts.telegram}` : "",
    },
    { label: t("messages:card.phone"), value: card.contacts.phone ?? "" },
    { label: t("messages:card.email"), value: card.contacts.email ?? "" },
    { label: t("messages:card.company"), value: card.contacts.company ?? "" },
  ].filter((row) => row.value);
  const facts = factRows(t, card.facts);
  return (
    <div className="pf-fp-stack">
      <div className="pf-fp-stack" style={{ gap: 4 }}>
        <h3 className="pf-fp-title">{card.name}</h3>
        <div className="pf-fp-row" style={{ alignItems: "center" }}>
          <span className="pf-hint">{card.lead}</span>
          <StatusTag kind="lead" status={card.status} />
        </div>
      </div>

      <div className="pf-fp-block">
        <h4>{t("leads:card.contacts")}</h4>
        {contacts.length ? (
          <DefinitionList items={contacts} />
        ) : (
          <p className="pf-fp-sub">{t("leads:card.none")}</p>
        )}
      </div>

      <div className="pf-fp-block">
        <h4>{t("leads:card.about")}</h4>
        <DefinitionList
          items={[
            { label: t("leads:card.channel"), value: channelLabel(t, card.channel) },
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
                  style={{ padding: 0 }}
                  to={clientPath(card.client.id)}
                >
                  {card.client.name}
                </LinkButton>
              ) : null,
            },
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

      <div className="pf-fp-block">
        <h4>{t("leads:card.facts")}</h4>
        {card.need ? (
          <DefinitionList items={[{ label: t("leads:card.need"), value: card.need }]} />
        ) : null}
        {facts.length ? (
          <DefinitionList items={facts} />
        ) : card.need ? null : (
          <p className="pf-fp-sub">{t("leads:card.none")}</p>
        )}
      </div>

      <div className="pf-fp-block">
        <h4>{t("leads:card.messages")}</h4>
        {card.last_messages.length ? (
          <ol className="pf-crm-messages" aria-label={t("leads:card.messages")}>
            {card.last_messages.map((message, index) => (
              <li key={index} className="pf-crm-message" data-author={message.author}>
                <span className="pf-hint">
                  {t(`leads:card.authors.${message.author}`)} · {fmt.date(message.at, "datetime")}
                </span>
                <span className="pf-crm-message-text">{message.text}</span>
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
            type="primary"
            to={`/crm/leads?lead=${card.lead}&create=1&panel=open&tab=card`}
          >
            {t("leads:actions.create")}
          </LinkButton>
        ) : null}
        <LinkButton to={`/crm/messages?lead=${card.lead}`}>{t("leads:actions.reply")}</LinkButton>
        {sheet ? <Button onClick={onClose}>{t("leads:card.close")}</Button> : null}
      </div>
    </div>
  );
}

/**
 * Карточка лида в боковом окне (SPEC-v3 §7.2): контакты и каналы, согласие на данные, факты квалификации от бота, последние
 * сообщения, срок первого ответа и итог подтверждения заявки клиенту (D1-9). Отсюда — «Создать заявку» и «Ответить».
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
