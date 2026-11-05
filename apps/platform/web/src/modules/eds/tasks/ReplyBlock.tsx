import { Card } from "antd";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import type { LetterCard, LetterReply } from "../../../shared/api/generated/model";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { StatusTag } from "../../../shared/ui/StatusTag";

/** Слова блока «Ответ» (EDS-REPLY-1): где ответ на входящее — черновик, передан, ИСХ и итог его отправки. */
function useReplyText() {
  const { t } = useTranslation("letters");
  return (reply: LetterReply): string => {
    const number = reply.number ?? "";
    if (reply.state === "draft") return t("reply.draft");
    if (reply.state === "registration_requested") return t("reply.handed");
    if (reply.mail === "failed") {
      return reply.mail_reason
        ? t("reply.failed", { number, reason: reply.mail_reason })
        : t("reply.failedNoReason", { number });
    }
    if (reply.mail === "sending") return t("reply.sending", { number });
    if (reply.mail === "sent") return t("reply.sent", { number });
    return `${t("reply.registered", { number })} ${t("reply.noMail")}`;
  };
}

/** Один ответ: слова, метка «Не отправлено» и действие — «Продолжить ответ» (свой черновик) или «Открыть». */
function ReplyItem({ reply }: { reply: LetterReply }) {
  const { t } = useTranslation("letters");
  const { me } = useAuth();
  const text = useReplyText();
  const mineDraft = reply.state === "draft" && reply.author.id === me.id;
  const failed = reply.state === "registered" && reply.mail === "failed";
  return (
    <li className="pf-reply-item">
      <p className="pf-reply-text">
        {failed ? <StatusTag tone="red">{t("reply.failedTag")}</StatusTag> : null} {text(reply)}
      </p>
      {failed ? <p className="pf-hint">{t("reply.failedHint")}</p> : null}
      <LinkButton
        size="small"
        to={mineDraft ? `/eds/new?draft=${reply.document_id}` : reply.path}
        aria-label={`${mineDraft ? t("reply.continue") : t("reply.open")}: ${reply.subject}`}
      >
        {mineDraft ? t("reply.continue") : t("reply.open")}
      </LinkButton>
    </li>
  );
}

/**
 * Блок «Ответ на письмо» в карточке ВХ и на рабочем экране поручения (EDS-REPLY-1): связь ВХ → ИСХ видна с обеих сторон.
 * Пусто — блока нет.
 */
export function ReplyCard({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const replies = letter.replies ?? [];
  if (replies.length === 0) return null;
  return (
    <Card size="small" title={<h2 className="pf-letters-title">{t("reply.title")}</h2>}>
      <ul className="pf-reply-list">
        {replies.map((reply) => (
          <ReplyItem key={reply.document_id} reply={reply} />
        ))}
      </ul>
    </Card>
  );
}
