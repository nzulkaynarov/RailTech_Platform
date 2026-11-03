import { useTranslation } from "react-i18next";

import { StatusTag } from "../../../shared/ui/StatusTag";

import type {
  InboundMail,
  InboundMailAddress,
  InboundMailAttachment,
  InboundMailMessage,
} from "../../../shared/api/generated/model";
import { getDownloadInboundMailAttachmentUrl } from "../../../shared/api/generated/platform-bff";
import { formatFileSize } from "../../../shared/lib/fileSize";
import { useFormat } from "../../../shared/lib/useFormat";
import { timeline } from "./mailModel";

/** Адреса письма словами: «Иванов (сотрудник), client@…», общий ящик помечен. */
export function AddressList({ items }: { items: readonly InboundMailAddress[] }) {
  const { t } = useTranslation("letters");
  if (items.length === 0) return null;
  return (
    <>
      {items
        .map((a) =>
          a.staff
            ? t("mail.address.staff", { name: a.staff.name, email: a.email })
            : a.mailbox
              ? t("mail.address.mailbox", { email: a.email })
              : a.email,
        )
        .join(", ")}
    </>
  );
}

function Files({ mailId, files }: { mailId: number; files: readonly InboundMailAttachment[] }) {
  const { t, i18n } = useTranslation("letters");
  if (files.length === 0) return null;
  return (
    <ul className="pf-res-files" aria-label={t("mail.files")}>
      {files.map((file) => (
        <li key={file.index}>
          <a
            className="pf-focusable pf-res-file"
            href={getDownloadInboundMailAttachmentUrl(mailId, file.index)}
            download
            aria-label={t("mail.download", { name: file.name })}
          >
            {file.name}
          </a>
          <span className="pf-hint">{formatFileSize(file.size, i18n.language)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Одно письмо клиента в переписке; у первого — что не принято и «письмо слишком большое». */
function Incoming({
  message,
  first,
  mail,
}: {
  message: InboundMailMessage;
  first: boolean;
  mail: InboundMail;
}) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  return (
    <li className="pf-mail-entry">
      <p className="pf-hint pf-mail-entry-head">
        {t("mail.thread.incoming", {
          sender: message.from_name || message.from_email,
          when: date(message.at, "datetime"),
        })}
        {message.new_participant ? (
          <>
            {" "}
            <StatusTag tone="gold">{t("mail.thread.newParticipant")}</StatusTag>
          </>
        ) : null}
      </p>
      <pre className="pf-mail-text">{message.text}</pre>
      <Files mailId={message.id} files={message.attachments} />
      {first
        ? mail.skipped.map((file) => (
            <p key={file.name} className="pf-hint pf-mail-what">
              {t("mail.skipped", {
                name: file.name,
                reason: t(`mail.skippedReason.${file.reason}`),
              })}
            </p>
          ))
        : null}
    </li>
  );
}

export function Thread({ mail }: { mail: InboundMail }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const entries = timeline(mail);
  return (
    <ol className="pf-mail-thread" aria-label={t("mail.thread.title")}>
      {entries.map((entry) =>
        entry.kind === "in" ? (
          <Incoming
            key={`in-${String(entry.message.id)}`}
            message={entry.message}
            first={entry.message.id === mail.id}
            mail={mail}
          />
        ) : (
          <li key={`out-${String(entry.reply.id)}`} className="pf-mail-entry pf-mail-entry--out">
            <p className="pf-hint pf-mail-entry-head">
              {t("mail.thread.outgoing", {
                who: entry.reply.by?.name ?? t("mail.journal.system"),
                when: date(entry.at, "datetime"),
                to: entry.reply.to_email,
                subject: entry.reply.subject,
              })}
              {" · "}
              {t(`mail.reply.status.${entry.reply.status}`, { defaultValue: entry.reply.status })}
            </p>
          </li>
        ),
      )}
    </ol>
  );
}

/** Журнал письма: кто взял, что сделал, когда — без текстов писем. */
export function Journal({ mail }: { mail: InboundMail }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  if (mail.journal.length === 0) return null;
  return (
    <section aria-labelledby="mail-journal-title">
      <h3 id="mail-journal-title" className="pf-res-subhead">
        {t("mail.journal.title")}
      </h3>
      <ul className="pf-mail-journal">
        {mail.journal.map((event, index) => (
          <li key={`${event.at}-${String(index)}`} className="pf-hint">
            {date(event.at, "datetime")} · {event.actor?.name ?? t("mail.journal.system")} ·{" "}
            {t(`mail.journal.action.${event.action}`, { defaultValue: event.action })}
            {event.detail ? ` — ${event.detail}` : ""}
          </li>
        ))}
      </ul>
    </section>
  );
}
