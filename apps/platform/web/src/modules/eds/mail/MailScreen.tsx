import { Card, Skeleton } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { InboundMailItem } from "../../../shared/api/generated/model";
import { useListInboundMail } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { MailView } from "./MailView";
import { ADMIN_MAIL_PATH, mailPath } from "./mailModel";

import "../inbox/inbox.css";
import "./mail.css";

function Row({ mail }: { mail: InboundMailItem }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const subject = mail.subject || t("mail.noSubject");
  const kind = mail.assist.status === "done" && mail.assist.kind ? mail.assist.kind : null;
  return (
    <li className="pf-mail-row">
      <div className="pf-mail-row-head">
        <Link
          className="pf-focusable pf-mail-subject"
          to={mailPath(mail.id)}
          aria-label={t("mail.open", { subject })}
        >
          {subject}
        </Link>
        <span className="pf-hint">{date(mail.received_at, "datetime")}</span>
      </div>
      <p className="pf-mail-sender">
        {mail.from_name ? `${mail.from_name} · ${mail.from_email}` : mail.from_email}
        {mail.client ? ` · ${mail.client.name}` : ""}
      </p>
      <p className="pf-hint pf-mail-preview">{mail.assist.summary ?? mail.preview}</p>
      <div className="pf-fp-row">
        {kind ? <StatusTag tone="blue">{t(`mail.kind.${kind}`)}</StatusTag> : null}
        {mail.attachments_count > 0 ? (
          <span className="pf-hint">
            {t("mail.attachments", { count: mail.attachments_count })}
          </span>
        ) : null}
      </div>
    </li>
  );
}

function MailList() {
  const { t } = useTranslation(["letters", "modules"]);
  const { me } = useAuth();
  const query = useListInboundMail();
  const title = t("modules:eds.sections.mail");
  useDocumentTitle(title);
  const data = query.data;
  let body;
  if (query.isPending) {
    body = <Skeleton active paragraph={{ rows: 6 }} />;
  } else if (!data) {
    body = (
      <EmptyState
        title={t("letters:state.loadError.title")}
        text={t("letters:state.loadError.text")}
      />
    );
  } else if (!data.mailbox.configured) {
    body = (
      <EmptyState
        title={t("letters:mail.off.title")}
        text={t("letters:mail.off.text")}
        action={
          canSee(me, { resource: "admin" }) ? (
            <LinkButton to={ADMIN_MAIL_PATH}>{t("letters:mail.off.action")}</LinkButton>
          ) : undefined
        }
      />
    );
  } else if (data.items.length === 0) {
    body = <EmptyState title={t("letters:mail.empty.title")} text={t("letters:mail.empty.text")} />;
  } else {
    body = (
      <Card>
        <ul className="pf-mail-list" aria-label={t("letters:mail.caption")}>
          {data.items.map((mail) => (
            <Row key={mail.id} mail={mail} />
          ))}
        </ul>
      </Card>
    );
  }
  return (
    <div className="pf-mail">
      <PageHeader title={title} subtitle={t("letters:mail.subtitle")} />
      {body}
    </div>
  );
}

/** Документы · Входящая почта (W18A-P2): очередь `/eds/mail` или карточка письма `/eds/mail/:id`. */
export function MailScreen({ objectId }: { objectId?: string | undefined }) {
  const id = Number(objectId);
  return objectId && Number.isInteger(id) && id > 0 ? <MailView id={id} /> : <MailList />;
}
