import { Button, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useFormat } from "../../shared/lib/useFormat";
import { useGetMyTicket, useListMyTickets } from "../../shared/api/generated/platform-bff";
import { DefinitionList } from "../../shared/ui/DefinitionList";
import { EmptyState } from "../../shared/ui/EmptyState";
import { TicketStatusTag } from "./ticketUi";
import { WriteToAdminModal } from "./WriteToAdminModal";

import "../help/help.css";

/** «Мои обращения»: свои обращения к администратору с статусом; другие сотрудники их не видят. */
export function MyRequests({ number }: { number?: string }) {
  if (number) return <MyRequest number={number} />;
  return <MyRequestList />;
}

function MyRequestList() {
  const { t } = useTranslation("help");
  const format = useFormat();
  const list = useListMyTickets();
  const [writing, setWriting] = useState(false);
  const modal = writing ? (
    <WriteToAdminModal
      open
      onClose={() => {
        setWriting(false);
      }}
    />
  ) : null;
  const write = (
    <Button
      type="primary"
      onClick={() => {
        setWriting(true);
      }}
    >
      {t("requests.write")}
    </Button>
  );
  if (list.isPending) return <Skeleton active paragraph={{ rows: 4 }} title={false} />;
  if (list.isError) {
    return (
      <EmptyState
        title={t("requests.loadError")}
        text={t("requests.loadErrorText")}
        action={
          <Button
            onClick={() => {
              void list.refetch();
            }}
          >
            {t("requests.retry")}
          </Button>
        }
      />
    );
  }
  const items = list.data.items;
  return (
    <div className="pf-help-block">
      <p style={{ margin: 0 }}>{t("requests.intro")}</p>
      {items.length === 0 ? (
        <EmptyState title={t("requests.empty")} text={t("requests.emptyText")} action={write} />
      ) : (
        <>
          <div>{write}</div>
          <ul className="pf-help-list" aria-label={t("requests.listLabel")}>
            {items.map((item) => (
              <li key={item.number}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <Link
                    to={`/help/requests/${encodeURIComponent(item.number)}`}
                    className="pf-help-link pf-focusable"
                    aria-label={t("requests.open", { number: item.number })}
                  >
                    {item.number}
                  </Link>
                  <span>{t(`ticket.subject.${item.subject}`)}</span>
                  <TicketStatusTag status={item.status} />
                </div>
                <div className="pf-hint">{item.preview}</div>
                <div className="pf-hint">{format.activity(item.updated_at)}</div>
              </li>
            ))}
          </ul>
        </>
      )}
      {modal}
    </div>
  );
}

function MyRequest({ number }: { number: string }) {
  const { t } = useTranslation("help");
  const format = useFormat();
  const one = useGetMyTicket(number);
  if (one.isPending) return <Skeleton active paragraph={{ rows: 5 }} title={false} />;
  if (one.isError) {
    return (
      <div className="pf-help-block">
        <EmptyState
          title={t("requests.notFound")}
          text={t("requests.notFoundText")}
          action={
            <Link to="/help/requests" className="pf-help-link pf-focusable">
              {t("requests.back")}
            </Link>
          }
        />
      </div>
    );
  }
  const ticket = one.data;
  return (
    <div className="pf-help-block">
      <Link to="/help/requests" className="pf-help-link pf-focusable">
        {t("requests.back")}
      </Link>
      <h2 style={{ margin: 0, fontSize: 16, lineHeight: "24px" }}>
        {ticket.number} · {t(`ticket.subject.${ticket.subject}`)}
      </h2>
      <DefinitionList
        items={[
          { label: t("admin.card.status"), value: <TicketStatusTag status={ticket.status} /> },
          { label: t("requests.page"), value: ticket.page },
          { label: t("requests.sent"), value: format.activity(ticket.created_at) },
        ]}
      />
      <section aria-labelledby="my-ticket-text">
        <h3 id="my-ticket-text" style={{ margin: "0 0 4px", fontSize: 14 }}>
          {t("requests.yourText")}
        </h3>
        <p className="pf-ticket-body">{ticket.body}</p>
      </section>
      <section aria-labelledby="my-ticket-answers">
        <h3 id="my-ticket-answers" style={{ margin: "0 0 4px", fontSize: 14 }}>
          {t("requests.answers")}
        </h3>
        {ticket.messages.length === 0 ? (
          <p className="pf-hint" style={{ margin: 0 }}>
            {t("requests.noAnswers")}
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
    </div>
  );
}
