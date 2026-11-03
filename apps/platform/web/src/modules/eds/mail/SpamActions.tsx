import { Alert, App, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { ApiError } from "../../../shared/api/errors";
import type { InboundMail } from "../../../shared/api/generated/model";
import {
  discardInboundMail,
  markInboundMailNotSpam,
} from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { SPAM_TAB_PATH } from "./mailModel";

/**
 * Подозрительное письмо из папки «Спам» (W18A-P2-2; эталон — Zendesk «Suspended tickets»): «Не спам → в очередь» —
 * обычное «Ждёт разбора», «Убрать» — в архив с причиной «Спам». Ящик на сервере не меняется (только чтение), поэтому
 * подсказка — отметить отправителя «Не спам» в самой почте.
 */
export function SpamActions({ mail, onDone }: { mail: InboundMail; onDone: () => void }) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [pending, setPending] = useState<"keep" | "drop" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async (kind: "keep" | "drop") => {
    setPending(kind);
    setError(null);
    try {
      if (kind === "keep") {
        await markInboundMailNotSpam(mail.id);
        void message.success(t("mail.spam.notSpamDone"));
      } else {
        await discardInboundMail(mail.id);
        void message.success(t("mail.spam.discardDone"));
      }
      onDone();
      void navigate(SPAM_TAB_PATH);
    } catch (failure) {
      const reason = failure instanceof ApiError ? failure.message : String(failure);
      setError(t("mail.actions.failed", { reason }));
    } finally {
      setPending(null);
    }
  };
  return (
    <section aria-labelledby="mail-spam-title" className="pf-mail-actions">
      <h3 id="mail-spam-title" className="pf-res-subhead">
        {t("mail.spam.title")}
      </h3>
      <p className="pf-mail-what">{t("mail.spam.what")}</p>
      <Consequence
        title={t("mail.actions.what")}
        items={[t("mail.spam.notSpamWhat"), t("mail.spam.discardWhat")]}
      />
      <div className="pf-fp-row">
        <Button
          type="primary"
          loading={pending === "keep"}
          disabled={pending !== null}
          onClick={() => void run("keep")}
        >
          {t("mail.spam.notSpam")}
        </Button>
        <Button
          loading={pending === "drop"}
          disabled={pending !== null}
          onClick={() => void run("drop")}
        >
          {t("mail.spam.discard")}
        </Button>
      </div>
      <p className="pf-hint pf-mail-what">{t("mail.spam.hint")}</p>
      {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
    </section>
  );
}
