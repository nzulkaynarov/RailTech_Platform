import { Alert, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { InboundMail } from "../../../shared/api/generated/model";
import { assistInboundMail } from "../../../shared/api/generated/platform-bff";

function reasonOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/** Подсказка помощника канцелярии: только по кнопке, ничего не делает сама (решение юриста 2026-11-02). */
export function Assist({ mail, onChange }: { mail: InboundMail; onChange: () => void }) {
  const { t } = useTranslation("letters");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { assist } = mail;
  if (assist.status === "off") return null;
  const ask = async () => {
    setPending(true);
    setError(null);
    try {
      await assistInboundMail(mail.id);
      onChange();
    } catch (failure) {
      setError(reasonOf(failure, t("mail.assist.unavailable")));
    } finally {
      setPending(false);
    }
  };
  return (
    <section aria-labelledby="mail-assist-title" className="pf-mail-actions">
      <h3 id="mail-assist-title" className="pf-res-subhead">
        {t("mail.assist.title")}
      </h3>
      {assist.status === "done" ? (
        <>
          {assist.summary ? <p className="pf-mail-what">{assist.summary}</p> : null}
          {mail.type === null || mail.type.source === "ai" ? (
            <p className="pf-hint pf-mail-what">
              {t(mail.type === null ? "mail.assist.noType" : "mail.assist.suggestsType")}
            </p>
          ) : null}
          <p className="pf-hint pf-mail-what">{t("mail.assist.note")}</p>
        </>
      ) : (
        <>
          <p className="pf-hint pf-mail-what">
            {assist.status === "unavailable"
              ? t("mail.assist.unavailable")
              : t("mail.assist.intro")}
          </p>
          <div>
            <Button loading={pending} onClick={() => void ask()}>
              {assist.status === "unavailable" ? t("mail.assist.retry") : t("mail.assist.button")}
            </Button>
          </div>
        </>
      )}
      {error ? <Alert type="warning" showIcon role="status" message={error} /> : null}
    </section>
  );
}
