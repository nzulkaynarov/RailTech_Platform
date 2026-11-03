import { Button, Drawer } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { InboundMailMessage } from "../../../shared/api/generated/model";
import { MailHtml } from "./MailHtml";
import { previewText } from "./frameDoc";

/** Строк письма в компактном виде карточки (Gmail, Front, Help Scout: превью, остальное — по клику). */
export const PREVIEW_LINES = 8;

/** Цитата прошлой переписки и подпись — свёрнуты под «…», как в Gmail. */
function QuoteToggle({ tail }: { tail: string }) {
  const { t } = useTranslation("letters");
  const [open, setOpen] = useState(false);
  if (tail === "") return null;
  return (
    <div className="pf-mail-quote">
      <button
        type="button"
        className="pf-mail-ellipsis pf-focusable"
        aria-expanded={open}
        aria-label={t(open ? "mail.view.quoteHide" : "mail.view.quote")}
        onClick={() => {
          setOpen((prev) => !prev);
        }}
      >
        …
      </button>
      {open ? <pre className="pf-mail-text pf-mail-text--quote">{tail}</pre> : null}
    </div>
  );
}

/** Письмо целиком: HTML во фрейме, если есть, иначе весь текст; цитата — под «…». */
function FullMail({ message, subject }: { message: InboundMailMessage; subject: string }) {
  return message.html !== null ? (
    <MailHtml html={message.html} remoteImages={message.html_remote_images} subject={subject} />
  ) : (
    <>
      <pre className="pf-mail-text">{message.text}</pre>
      <QuoteToggle tail={message.text_tail} />
    </>
  );
}

/**
 * Тело входящего письма в карточке (W18A-P2-4): первые строки текста без цитаты и подписи, «…» с цитатой и
 * «Открыть письмо полностью» (шторка на всю ширину: HTML рассылки во фрейме, картинки по кнопке). Внутренней
 * прокрутки нет.
 */
export function MailBody({ message, subject }: { message: InboundMailMessage; subject: string }) {
  const { t } = useTranslation("letters");
  const [full, setFull] = useState(false);
  const preview = previewText(message.text, PREVIEW_LINES);
  const canOpen = preview.more || message.html !== null;
  return (
    <>
      <pre className="pf-mail-text">{preview.shown}</pre>
      {preview.more ? (
        <span className="pf-hint" aria-hidden="true">
          …
        </span>
      ) : null}
      <QuoteToggle tail={message.text_tail} />
      {canOpen ? (
        <Button
          size="small"
          className="pf-mail-open"
          onClick={() => {
            setFull(true);
          }}
        >
          {t("mail.view.openFull")}
        </Button>
      ) : null}
      <Drawer
        open={full}
        onClose={() => {
          setFull(false);
        }}
        title={subject}
        width="min(100vw, 960px)"
        destroyOnHidden
      >
        <FullMail message={message} subject={subject} />
      </Drawer>
    </>
  );
}
