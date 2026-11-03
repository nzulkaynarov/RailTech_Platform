import { Alert, App, Button, Card, Checkbox, Input, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { InboundMail } from "../../../shared/api/generated/model";
import { replyInboundMail } from "../../../shared/api/generated/platform-bff";
import { inWorkByOther, useRefreshMail } from "./mailModel";

/**
 * Ответ из карточки в ту же цепочку. «Ответить» — только отправителю, «Ответить всем» — с копией остальным адресам письма
 * (без самого общего ящика). Обычный ответ делает письмо «Разобрано: ответ отправлен»; «Ждём ответа» оставляет его в работе.
 */
export function Reply({ mail, reload }: { mail: InboundMail; reload: () => void }) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const refresh = useRefreshMail();
  const [text, setText] = useState("");
  const [awaiting, setAwaiting] = useState(false);
  // «Кому» — явно (Zendesk, Help Scout): по умолчанию отправитель корня цепочки, список — адреса цепочки.
  const [chosen, setChosen] = useState<string | null>(null);
  const to = chosen !== null && mail.reply_options.includes(chosen) ? chosen : mail.reply_to;
  const [pending, setPending] = useState<"one" | "all" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const copy = mail.reply_all_copy;
  const closed = mail.status === "done" || mail.status === "spam";
  const send = async (all: boolean) => {
    setPending(all ? "all" : "one");
    setError(null);
    try {
      await replyInboundMail(mail.id, { text: text.trim(), to, reply_all: all, awaiting });
      setText("");
      void message.success(t(awaiting ? "mail.reply.sentAwaiting" : "mail.reply.sent"));
      await refresh();
      reload();
    } catch (failure) {
      const reason = failure instanceof ApiError ? failure.message : String(failure);
      setError(t("mail.actions.failed", { reason }));
      if (inWorkByOther(failure)) reload();
    } finally {
      setPending(null);
    }
  };
  if (closed) return null;
  return (
    <Card size="small" title={<h2 className="pf-letters-title">{t("mail.reply.title")}</h2>}>
      <div className="pf-mail-actions">
        <label htmlFor="mail-reply-to">{t("mail.reply.to")}</label>
        <Select
          id="mail-reply-to"
          value={to}
          options={mail.reply_options.map((value) => ({ value, label: value }))}
          onChange={setChosen}
        />
        <label htmlFor="mail-reply-text">{t("mail.reply.label")}</label>
        <Input.TextArea
          id="mail-reply-text"
          rows={4}
          maxLength={20000}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        <Checkbox
          checked={awaiting}
          onChange={(event) => {
            setAwaiting(event.target.checked);
          }}
        >
          {t("mail.reply.awaiting")}
        </Checkbox>
        <p className="pf-hint pf-mail-what">{t("mail.reply.what")}</p>
        {copy.length > 0 ? (
          <p className="pf-hint pf-mail-what">{t("mail.reply.copy", { list: copy.join(", ") })}</p>
        ) : null}
        <div className="pf-fp-row">
          <Button
            loading={pending === "one"}
            disabled={!text.trim() || pending !== null}
            onClick={() => void send(false)}
          >
            {t("mail.reply.send")}
          </Button>
          <Button
            loading={pending === "all"}
            disabled={!text.trim() || copy.length === 0 || pending !== null}
            onClick={() => void send(true)}
          >
            {t("mail.reply.sendAll")}
          </Button>
        </div>
        {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
      </div>
    </Card>
  );
}
