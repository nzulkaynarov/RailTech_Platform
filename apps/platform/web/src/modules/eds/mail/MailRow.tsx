import { Button, Checkbox } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { InboundMailItem } from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { arrivedAt, canReturn, mailPath, statusKey } from "./mailModel";
import { MailOutcome } from "./MailOutcome";

/** Строка списка «Входящая почта»: жирная тема, пока письмо не прочитано; кто ведёт, итог и «Вернуть в Новые». */
export function MailRow({
  mail,
  own,
  personalLabel,
  selected,
  onSelect,
  onReturn,
}: {
  mail: InboundMailItem;
  own: boolean;
  personalLabel: string;
  /** `undefined` — выбирать письма нельзя (личный режим, вкладка «Разобранные») */
  selected?: boolean | undefined;
  onSelect?: ((checked: boolean) => void) | undefined;
  onReturn: (mail: InboundMailItem) => void;
}) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const subject = mail.subject || t("mail.noSubject");
  const kind = mail.assist.status === "done" && mail.assist.kind ? mail.assist.kind : null;
  const working = mail.status === "in_work" || mail.status === "registering";
  return (
    <li className="pf-mail-row" data-unread={mail.unread || undefined}>
      {onSelect ? (
        <Checkbox
          className="pf-mail-select"
          checked={selected === true}
          aria-label={t("mail.select", { subject })}
          onChange={(event) => {
            onSelect(event.target.checked);
          }}
        />
      ) : null}
      <div className="pf-mail-row-main">
        <div className="pf-mail-row-head">
          <Link
            className={`pf-focusable pf-mail-subject${mail.unread ? " pf-mail-unread" : ""}`}
            to={mailPath(mail.id, own)}
            aria-label={t("mail.open", { subject })}
          >
            {subject}
          </Link>
          {mail.unread ? <span className="pf-mail-sr">{t("mail.unread")}</span> : null}
          <span className="pf-hint">{date(arrivedAt(mail), "datetime")}</span>
        </div>
        <p className="pf-mail-sender">
          {mail.from_name ? `${mail.from_name} · ${mail.from_email}` : mail.from_email}
          {mail.client ? ` · ${mail.client.name}` : ""}
        </p>
        <p className="pf-hint pf-mail-preview">{mail.assist.summary ?? mail.preview}</p>
        <div className="pf-fp-row">
          <StatusTag kind="inboundMail" status={mail.status}>
            {t(statusKey(mail))}
          </StatusTag>
          {working && mail.assignee ? (
            <span className="pf-hint">
              {t("mail.inWorkBy", {
                name: mail.assignee.name,
                time: mail.assigned_at ? date(mail.assigned_at, "time") : "",
              })}
            </span>
          ) : null}
          {mail.status === "new" && mail.thread_reply && mail.assignee ? (
            <span className="pf-hint">{t("mail.previous", { name: mail.assignee.name })}</span>
          ) : null}
          {mail.eds_waiting ? <StatusTag tone="gold">{t("mail.waiting")}</StatusTag> : null}
          {mail.personal ? <StatusTag tone="blue">{personalLabel}</StatusTag> : null}
          {mail.messages_count > 1 ? (
            <span className="pf-hint">{t("mail.messages", { count: mail.messages_count })}</span>
          ) : null}
          {mail.from_history ? <StatusTag tone="default">{t("mail.historyTag")}</StatusTag> : null}
          {kind ? <StatusTag tone="blue">{t(`mail.kind.${kind}`)}</StatusTag> : null}
          {mail.attachments_count > 0 ? (
            <span className="pf-hint">
              {t("mail.attachments", { count: mail.attachments_count })}
            </span>
          ) : null}
        </div>
        {mail.status === "done" && mail.result ? (
          <p className="pf-mail-result">
            <MailOutcome result={mail.result} />
            {mail.result.by ? (
              <span className="pf-hint">
                {" · "}
                {mail.result.by.name}
                {mail.result.at ? `, ${date(mail.result.at, "datetime")}` : ""}
              </span>
            ) : null}
          </p>
        ) : null}
      </div>
      {!own && canReturn(mail) ? (
        <Button
          size="small"
          className="pf-mail-return"
          onClick={() => {
            onReturn(mail);
          }}
        >
          {t("mail.returnToNew")}
        </Button>
      ) : null}
    </li>
  );
}
