import { Alert, Button, Select, Skeleton } from "antd";
import type { TFunction } from "i18next";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { ApiError } from "../../../shared/api/errors";
import type {
  ClientCard,
  ClientContactView,
  ClientInvitation,
  ClientRequestRow,
  InvitationResendInChannel,
} from "../../../shared/api/generated/model";
import {
  useGetCrmClient,
  useResendCrmClientInvitation,
  useRetryCrmRequest,
} from "../../../shared/api/generated/platform-bff";
import type { StageOrLost } from "../../../shared/lib/statuses";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { DocNumber } from "../../../shared/ui/DocNumber";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { RequestSteps } from "../../../shared/ui/RequestSteps";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { reasonError } from "../common/errors";
import { useRefreshCrm } from "../common/params";
import { transferReason } from "./labels";

import "../crm.css";

function Contact({ contact }: { contact: ClientContactView }) {
  const { t } = useTranslation("clients");
  const rows = [
    contact.telegram ? `${t("card.channels.telegram")}: @${contact.telegram}` : null,
    contact.phone ? `${t("card.channels.phone")}: ${contact.phone}` : null,
    contact.email ? `${t("card.channels.email")}: ${contact.email}` : null,
  ].filter((row): row is string => row !== null);
  return (
    <li className="pf-crm-entry">
      <div className="pf-fp-row" style={{ alignItems: "center" }}>
        <strong>{contact.name}</strong>
        {contact.position ? <span className="pf-hint">{contact.position}</span> : null}
        {contact.is_primary ? <StatusTag tone="blue">{t("card.primary")}</StatusTag> : null}
      </div>
      {rows.length ? (
        <ul className="pf-crm-plain">
          {rows.map((row) => (
            <li key={row}>{row}</li>
          ))}
        </ul>
      ) : (
        <span className="pf-req-error">{t("card.noChannels")}</span>
      )}
      {contact.preferred_channel ? (
        <span className="pf-hint">
          {t("card.preferred", { channel: t(`card.resendChannels.${contact.preferred_channel}`) })}
        </span>
      ) : null}
    </li>
  );
}

function stageOf(row: ClientRequestRow): StageOrLost {
  return row.step;
}

function RequestItem({ row, canWrite }: { row: ClientRequestRow; canWrite: boolean }) {
  const { t } = useTranslation("clients");
  const fmt = useFormat();
  const refresh = useRefreshCrm();
  const retry = useRetryCrmRequest();
  const [failure, setFailure] = useState<string | null>(null);
  const [retried, setRetried] = useState(false);
  return (
    <li className="pf-crm-entry">
      <div className="pf-fp-row" style={{ alignItems: "center" }}>
        {row.number ? (
          <DocNumber number={row.number} />
        ) : (
          <span className="pf-hint">{t("card.noNumber")}</span>
        )}
        <strong className="pf-crm-wrap">{row.title}</strong>
        {row.urgency === "urgent" ? <StatusTag tone="red">{t("card.urgent")}</StatusTag> : null}
      </div>
      {row.summary ? <p className="pf-crm-wrap pf-fp-sub">{row.summary}</p> : null}
      <RequestSteps stage={stageOf(row)} {...(row.number ? { number: row.number } : {})} />
      <span className="pf-hint">
        {t("card.clientSees", { text: t(`clientSees.${row.client_sees}`) })} ·{" "}
        {fmt.date(row.created_at)}
      </span>
      {row.transfer === "pending" ? (
        <span className="pf-hint">{t("card.transfer.pending")}</span>
      ) : null}
      {row.transfer === "failed" ? (
        <div className="pf-fp-stack" style={{ gap: 8 }}>
          <span className="pf-req-error">
            {t("card.transfer.failed", { reason: transferReason(t, row.transfer_error) })}
          </span>
          {canWrite && row.transfer_error !== "erp_request_conflict" ? (
            <div>
              <Button
                size="small"
                loading={retry.isPending}
                aria-label={t("card.retryLabel", { title: row.title })}
                onClick={() => {
                  setFailure(null);
                  retry.mutate(
                    { deal: row.deal },
                    {
                      onSuccess: () => {
                        setRetried(true);
                        refresh();
                      },
                      onError: (error) => {
                        setFailure(reasonError(t, "request:errors", error));
                      },
                    },
                  );
                }}
              >
                {t("card.retry")}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
      {retried ? (
        <span role="status" className="pf-hint">
          {t("card.retried")}
        </span>
      ) : null}
      <ErrorNote message={failure} />
    </li>
  );
}

function invitationText(
  t: TFunction,
  fmt: ReturnType<typeof useFormat>,
  inv: ClientInvitation,
): string {
  const via = inv.sent_via.map((c) => t(`card.channels.${c}`, { defaultValue: c })).join(", ");
  if (inv.status === "sent") {
    return [
      t("leads:card.notice.sent", { date: inv.sent_at ? fmt.date(inv.sent_at, "datetime") : "" }),
      via,
      inv.contact_name,
    ]
      .filter(Boolean)
      .join(" · ");
  }
  if (inv.status === "failed") {
    return t("leads:card.notice.failed", { reason: inv.error_text ?? t("leads:card.none") });
  }
  return t(`leads:card.notice.${inv.status}`);
}

/** Приглашение в кабинет: итог последней отправки и «Отправить повторно другим каналом» (D1-9). */
function Invitation({ card, canWrite }: { card: ClientCard; canWrite: boolean }) {
  const { t } = useTranslation(["clients", "leads", "request"]);
  const fmt = useFormat();
  const refresh = useRefreshCrm();
  const resend = useResendCrmClientInvitation();
  const inv = card.invitation;
  const options = inv?.available_channels ?? ["email", "telegram", "both"];
  const [channel, setChannel] = useState<InvitationResendInChannel>(
    inv?.suggested_channel ?? options[0] ?? "email",
  );
  const [failure, setFailure] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  return (
    <div className="pf-fp-stack" style={{ gap: 8 }}>
      <p className="pf-fp-sub">
        {inv ? invitationText(t, fmt, inv) : t("clients:card.noInvitation")}
      </p>
      {canWrite && inv?.can_resend ? (
        <div className="pf-fp-row" style={{ alignItems: "flex-end" }}>
          <div className="pf-fp-field">
            <label htmlFor={`pf-client-${String(card.id)}-invite`}>
              {t("clients:card.resendChannel")}
            </label>
            <Select
              id={`pf-client-${String(card.id)}-invite`}
              style={{ minWidth: 180 }}
              value={channel}
              options={options.map((value) => ({
                value,
                label: t(`clients:card.resendChannels.${value}`),
              }))}
              onChange={(value) => {
                setChannel(value);
              }}
            />
          </div>
          <Button
            loading={resend.isPending}
            onClick={() => {
              setFailure(null);
              setSent(false);
              resend.mutate(
                { id: card.id, data: { channel } },
                {
                  onSuccess: () => {
                    setSent(true);
                    refresh();
                  },
                  onError: (error) => {
                    setFailure(reasonError(t, "request:errors", error));
                  },
                },
              );
            }}
          >
            {t("clients:card.resend")}
          </Button>
        </div>
      ) : null}
      {sent ? (
        <span role="status" className="pf-hint">
          {t("clients:card.resendDone")}
        </span>
      ) : null}
      <ErrorNote message={failure} />
    </div>
  );
}

function Partial({ card }: { card: ClientCard }) {
  const { t } = useTranslation("clients");
  const parts = (["contacts", "requests", "documents"] as const).filter(
    (part) => card.sources[part] === "unavailable",
  );
  if (parts.length === 0) return null;
  return (
    <Alert
      type="warning"
      showIcon
      role="status"
      message={t("card.partial", { parts: parts.map((p) => t(`card.parts.${p}`)).join(", ") })}
    />
  );
}

function Body({ card, sheet, onClose }: { card: ClientCard; sheet: boolean; onClose: () => void }) {
  const { t } = useTranslation(["clients", "dictionary"]);
  const fmt = useFormat();
  const { me } = useAuth();
  const canWrite = canEdit(me, "crm.clients");
  const handoff = card.handoff.status;
  return (
    <div className="pf-fp-stack">
      <div className="pf-fp-stack" style={{ gap: 4 }}>
        <h3 className="pf-fp-title">{card.name}</h3>
        <span className="pf-hint">
          {card.inn ? `${t("clients:card.inn")} ${card.inn}` : t("clients:card.noInn")}
        </span>
      </div>
      <Partial card={card} />
      <DefinitionList
        items={[
          { label: t("clients:card.segment"), value: card.segment },
          {
            label: t("clients:card.erp"),
            value:
              handoff === "failed" ? (
                <span className="pf-req-error">
                  {t("clients:handoff.failed")}: {transferReason(t, card.handoff.error)}
                </span>
              ) : handoff ? (
                t(`clients:handoff.${handoff}`)
              ) : card.in_erp ? (
                t("clients:inErp")
              ) : (
                t("clients:notInErp")
              ),
          },
        ]}
      />
      {canWrite ? (
        <div>
          <LinkButton
            type="primary"
            to={`/crm/clients?client=${String(card.id)}&create=1&panel=open&tab=card`}
          >
            {t("clients:card.newRequest")}
          </LinkButton>
        </div>
      ) : null}

      <section className="pf-fp-block" aria-labelledby={`pf-client-${String(card.id)}-contacts`}>
        <h4 id={`pf-client-${String(card.id)}-contacts`}>{t("clients:card.contacts")}</h4>
        {card.contacts.length ? (
          <ul className="pf-crm-entries">
            {card.contacts.map((contact) => (
              <Contact key={contact.id} contact={contact} />
            ))}
          </ul>
        ) : (
          <p className="pf-fp-sub">{t("clients:card.noContacts")}</p>
        )}
      </section>

      <section className="pf-fp-block" aria-labelledby={`pf-client-${String(card.id)}-leads`}>
        <h4 id={`pf-client-${String(card.id)}-leads`}>{t("clients:card.conversation")}</h4>
        {card.leads.length ? (
          <ul className="pf-crm-plain">
            {card.leads.map((link) => (
              <li key={link.lead}>
                <LinkButton
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  to={`/crm/messages?lead=${link.lead}`}
                  aria-label={t("clients:card.openConversation", { name: link.name })}
                >
                  {link.name} · {link.lead}
                </LinkButton>
                {link.last_message_at ? (
                  <span className="pf-hint"> · {fmt.activity(link.last_message_at)}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="pf-fp-sub">{t("clients:card.noLeads")}</p>
        )}
      </section>

      <section className="pf-fp-block" aria-labelledby={`pf-client-${String(card.id)}-requests`}>
        <h4 id={`pf-client-${String(card.id)}-requests`}>{t("clients:card.requests")}</h4>
        {card.requests.length ? (
          <ul className="pf-crm-entries">
            {card.requests.map((row) => (
              <RequestItem key={row.deal} row={row} canWrite={canWrite} />
            ))}
          </ul>
        ) : (
          <p className="pf-fp-sub">{t("clients:card.noRequests")}</p>
        )}
      </section>

      <section className="pf-fp-block" aria-labelledby={`pf-client-${String(card.id)}-docs`}>
        <h4 id={`pf-client-${String(card.id)}-docs`}>{t("clients:card.documents")}</h4>
        {card.documents.length ? (
          <ul className="pf-crm-plain">
            {card.documents.map((doc) => (
              <li key={doc.id} className="pf-crm-wrap">
                {t(`clients:card.docTypes.${doc.type}`)}
                {doc.number ? ` ${doc.number}` : ""} · {doc.title}
                {doc.date ? ` · ${fmt.date(doc.date)}` : ""}
                {doc.visible_to_client ? null : (
                  <span className="pf-hint"> · {t("clients:card.hiddenFromClient")}</span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="pf-fp-sub">{t("clients:card.noDocuments")}</p>
        )}
      </section>

      <section className="pf-fp-block" aria-labelledby={`pf-client-${String(card.id)}-invite-h`}>
        <h4 id={`pf-client-${String(card.id)}-invite-h`}>{t("clients:card.invitation")}</h4>
        <Invitation card={card} canWrite={canWrite} />
      </section>

      {sheet ? (
        <div className="pf-crm-actions" data-sheet={sheet}>
          <Button onClick={onClose}>{t("clients:card.close")}</Button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Карточка клиента 360° (SPEC-v3 §7.2): компания и ИНН, контакты с каналами, переписка, заявки и проекты со шкалой из
 * 7 шагов и тем, что видит клиент, документы, приглашение в кабинет. Ошибка передачи заявки в бэк-офис — словами и
 * «Повторить отправку в ERP» (B-082). Удалённый контакт CRM не отдаёт вовсе — в карточке только живые (B-030).
 */
export function ClientPanel({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation("clients");
  const { mobile } = useViewport();
  const query = useGetCrmClient(id);
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
