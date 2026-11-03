import { Alert, Card, Skeleton } from "antd";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { InboundMail } from "../../../shared/api/generated/model";
import { markInboundMailRead, useGetInboundMail } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { MailActions } from "./MailActions";
import { Reply } from "./MailReply";
import { AddressList, Journal, Thread } from "./MailThread";
import { arrivedAt, listPath, statusKey, useRefreshMail } from "./mailModel";

function Content({ mail, own, reload }: { mail: InboundMail; own: boolean; reload: () => void }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const { me } = useAuth();
  const subject = mail.subject || t("mail.noSubject");
  const mine = mail.assignee !== null && String(mail.assignee.id) === me.id;
  const held = mail.status === "in_work" && !mine;
  const single = mail.messages.length <= 1 && mail.replies.length === 0;
  return (
    <div className="pf-mail">
      <PageHeader
        title={subject}
        subtitle={mail.from_name ? `${mail.from_name} · ${mail.from_email}` : mail.from_email}
        extra={
          <div className="pf-fp-row">
            {mail.from_history ? (
              <StatusTag tone="default">{t("mail.historyTag")}</StatusTag>
            ) : null}
            {mail.personal ? <StatusTag tone="blue">{mail.personal_label}</StatusTag> : null}
            <StatusTag kind="inboundMail" status={mail.status}>
              {t(statusKey(mail))}
            </StatusTag>
          </div>
        }
      />
      <div className="pf-letters-grid">
        <div className="pf-letters-main">
          <Card
            size="small"
            title={
              <h2 className="pf-letters-title">{t(single ? "mail.text" : "mail.thread.title")}</h2>
            }
          >
            <DefinitionList
              items={[
                { label: t("mail.fields.from"), value: mail.from_email },
                {
                  label: t("mail.fields.to"),
                  value: mail.to.length > 0 ? <AddressList items={mail.to} /> : null,
                },
                {
                  label: t("mail.fields.cc"),
                  value: mail.cc.length > 0 ? <AddressList items={mail.cc} /> : null,
                },
                { label: t("mail.fields.received"), value: date(arrivedAt(mail), "datetime") },
                {
                  label: t(mail.status === "new" ? "mail.fields.previous" : "mail.fields.assignee"),
                  value: mail.assignee
                    ? mail.status === "new"
                      ? mail.assignee.name
                      : t("mail.inWorkSince", {
                          name: mail.assignee.name,
                          time: mail.assigned_at ? date(mail.assigned_at, "time") : "",
                        })
                    : null,
                },
                { label: t("mail.fields.client"), value: mail.client?.name ?? null },
                { label: t("mail.fields.lead"), value: mail.lead?.number ?? null },
                { label: t("mail.fields.inns"), value: mail.inns.join(", ") || null },
              ].filter((item) => item.value !== null && item.value !== "")}
            />
            {mail.too_large ? <Alert type="warning" showIcon message={t("mail.tooLarge")} /> : null}
            <Thread mail={mail} />
          </Card>
          {held || (own && !mine) ? null : <Reply mail={mail} reload={reload} />}
          <Card size="small">
            <Journal mail={mail} />
          </Card>
        </div>
        <aside className="pf-letters-side" aria-label={t("mail.actions.title")}>
          <Card size="small">
            <MailActions mail={mail} own={own} reload={reload} />
          </Card>
        </aside>
      </div>
    </div>
  );
}

/** Карточка письма общего ящика: переписка, адресаты, «в работе», действия по состоянию, ответ, журнал. */
export function MailView({ id, own = false }: { id: number; own?: boolean }) {
  const { t } = useTranslation(["letters", "modules"]);
  const query = useGetInboundMail(id);
  const refresh = useRefreshMail();
  const marked = useRef<number | null>(null);
  const mail = query.data;
  useDocumentTitle(mail?.subject || t("modules:eds.sections.mail"));
  // Открыл карточку — прочитано (один раз на письмо; отметка на человека).
  useEffect(() => {
    if (!mail || marked.current === mail.id) return;
    marked.current = mail.id;
    void markInboundMailRead(mail.id)
      .then(() => refresh())
      .catch(() => undefined);
  }, [mail, refresh]);
  if (query.isPending) {
    return (
      <div className="pf-mail">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }
  if (!mail) {
    const status = query.error instanceof ApiError ? query.error.status : 0;
    const missing = status === 404 || status === 403;
    return (
      <EmptyState
        title={t(missing ? "letters:state.notFound.title" : "letters:state.loadError.title")}
        text={t(missing ? "letters:state.notFound.text" : "letters:state.loadError.text")}
        action={<LinkButton to={listPath(own)}>{t("modules:eds.sections.mail")}</LinkButton>}
      />
    );
  }
  return <Content mail={mail} own={own} reload={() => void query.refetch()} />;
}
