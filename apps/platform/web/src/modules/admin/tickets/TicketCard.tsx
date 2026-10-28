import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Input, Skeleton } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canEdit } from "../../../app/access";
import { RT_TAG_TEXT } from "../../../app/tokens.generated";
import { useAuth } from "../../../app/auth/useAuth";
import { TICKET_TEXT_MAX, ticketErrorText } from "../../../features/tickets/ticketMeta";
import { TicketStatusTag } from "../../../features/tickets/ticketUi";
import type { Ticket, TicketStatus } from "../../../shared/api/generated/model";
import {
  getGetMenuCountersQueryKey,
  getGetTicketQueryKey,
  getListTicketsQueryKey,
  useGetTicket,
  useReplyTicket,
  useSetTicketStatus,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";

import "../../../features/help/help.css";

/** Внутренний путь страницы Платформы — ссылка; всё остальное — просто текст. */
function PageLink({ page }: { page?: string | undefined }) {
  const { t } = useTranslation("help");
  if (!page) return null;
  return page.startsWith("/") && !page.startsWith("//") ? (
    <Link
      to={page}
      className="pf-help-link pf-focusable"
      aria-label={`${t("admin.card.openPage")}: ${page}`}
    >
      {page}
    </Link>
  ) : (
    <>{page}</>
  );
}

/**
 * Карточка обращения в боковом окне (W15-H7): кто, с какой страницы, текст, ответы и «Ответить». Отвечает и меняет статус
 * администратор (`admin: full`); директор читает. Первый ответ на «Новое» берёт обращение «В работу».
 */
export function TicketCard({ number }: { number: string }) {
  const { t } = useTranslation("help");
  const { me } = useAuth();
  const format = useFormat();
  const queryClient = useQueryClient();
  const one = useGetTicket(number);
  const editable = canEdit(me, "admin");
  const replyId = useId();
  const [text, setText] = useState("");
  const [touched, setTouched] = useState(false);
  const [done, setDone] = useState<"saved" | "status" | null>(null);

  const refresh = (ticket: Ticket) => {
    queryClient.setQueryData(getGetTicketQueryKey(number), ticket);
    void queryClient.invalidateQueries({ queryKey: getListTicketsQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getGetMenuCountersQueryKey() });
  };
  const reply = useReplyTicket({
    mutation: {
      onSuccess: (ticket) => {
        setText("");
        setTouched(false);
        setDone("saved");
        refresh(ticket);
      },
    },
  });
  const setStatus = useSetTicketStatus({
    mutation: {
      onSuccess: (ticket) => {
        setDone("status");
        refresh(ticket);
      },
    },
  });

  if (one.isPending) return <Skeleton active paragraph={{ rows: 6 }} />;
  if (one.isError) {
    return (
      <EmptyState
        level={3}
        compact
        title={t("admin.card.notFound")}
        text={t("admin.card.notFoundText")}
      />
    );
  }
  const ticket = one.data;
  const trimmed = text.trim();
  const replyError =
    touched && trimmed === ""
      ? t("admin.card.replyRequired")
      : trimmed.length > TICKET_TEXT_MAX
        ? t("write.bodyTooLong")
        : undefined;
  const busy = reply.isPending || setStatus.isPending;
  const send = (status?: TicketStatus) => {
    setTouched(true);
    setDone(null);
    if (trimmed === "" || trimmed.length > TICKET_TEXT_MAX) return;
    reply.mutate({ number, data: { body: trimmed, ...(status ? { status } : {}) } });
  };
  const move = (status: TicketStatus) => {
    setDone(null);
    setStatus.mutate({ number, data: { status } });
  };
  const error = reply.isError ? reply.error : setStatus.isError ? setStatus.error : null;

  return (
    <div className="pf-help-block">
      <h3 style={{ margin: 0, fontSize: 16, lineHeight: "24px" }}>
        {ticket.number} · {t(`ticket.subject.${ticket.subject}`)}
      </h3>
      <DefinitionList
        items={[
          { label: t("admin.card.status"), value: <TicketStatusTag status={ticket.status} /> },
          { label: t("admin.card.from"), value: ticket.author.name },
          { label: t("admin.card.role"), value: ticket.author_role },
          { label: t("admin.card.page"), value: <PageLink page={ticket.page} /> },
          { label: t("requests.sent"), value: format.activity(ticket.created_at) },
        ]}
      />
      <section aria-labelledby={`${replyId}-text`}>
        <h4 id={`${replyId}-text`} style={{ margin: "0 0 4px", fontSize: 14 }}>
          {t("admin.card.text")}
        </h4>
        <p className="pf-ticket-body">{ticket.body}</p>
      </section>
      <section aria-labelledby={`${replyId}-answers`}>
        <h4 id={`${replyId}-answers`} style={{ margin: "0 0 4px", fontSize: 14 }}>
          {t("admin.card.answers")}
        </h4>
        {ticket.messages.length === 0 ? (
          <p className="pf-hint" style={{ margin: 0 }}>
            {t("admin.card.noAnswers")}
          </p>
        ) : (
          <ul className="pf-help-list">
            {ticket.messages.map((message, index) => (
              <li key={index} className="pf-ticket-reply" style={{ marginBottom: 8 }}>
                <div className="pf-hint">
                  {t("requests.answerFrom", {
                    name: message.author_name ?? "",
                    when: format.activity(message.created_at),
                  })}
                </div>
                <p className="pf-ticket-body">{message.body}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
      {editable ? (
        <section aria-label={t("admin.card.reply")} className="pf-help-block">
          {error ? (
            <Alert
              type="error"
              showIcon
              role="alert"
              message={ticketErrorText(t, "admin.card", error)}
            />
          ) : null}
          {done && !error ? (
            <div role="status" className="pf-hint" style={{ color: RT_TAG_TEXT["green"] }}>
              {done === "saved" ? t("admin.card.saved") : t("admin.card.statusSaved")}
            </div>
          ) : (
            <div role="status" />
          )}
          <div>
            <label htmlFor={replyId} style={{ display: "block", marginBottom: 4 }}>
              {t("admin.card.reply")}
            </label>
            <Input.TextArea
              id={replyId}
              rows={4}
              value={text}
              placeholder={t("admin.card.replyPlaceholder")}
              status={replyError ? "error" : undefined}
              onChange={(event) => {
                setText(event.target.value);
              }}
            />
            {replyError ? (
              <div role="alert" style={{ color: "#cf1322", fontSize: 13 }}>
                {replyError}
              </div>
            ) : null}
          </div>
          <Consequence
            title={t("admin.card.consequenceTitle")}
            items={[...(t("admin.card.consequence", { returnObjects: true }) as string[])]}
          />
          <div className="pf-help-actions">
            <Button
              type="primary"
              loading={reply.isPending}
              disabled={busy}
              onClick={() => {
                send();
              }}
            >
              {t("admin.card.send")}
            </Button>
            {ticket.status !== "resolved" ? (
              <Button
                disabled={busy}
                onClick={() => {
                  send("resolved");
                }}
              >
                {t("admin.card.sendResolve")}
              </Button>
            ) : null}
          </div>
          <div className="pf-help-actions">
            {ticket.status === "new" ? (
              <Button
                disabled={busy}
                onClick={() => {
                  move("in_progress");
                }}
              >
                {t("admin.card.toWork")}
              </Button>
            ) : null}
            {ticket.status === "in_progress" || ticket.status === "new" ? (
              <Button
                disabled={busy}
                onClick={() => {
                  move("resolved");
                }}
              >
                {t("admin.card.resolve")}
              </Button>
            ) : null}
            {ticket.status === "resolved" ? (
              <Button
                disabled={busy}
                onClick={() => {
                  move("in_progress");
                }}
              >
                {t("admin.card.reopen")}
              </Button>
            ) : null}
          </div>
        </section>
      ) : (
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("admin.card.readOnly")}
        </p>
      )}
    </div>
  );
}
