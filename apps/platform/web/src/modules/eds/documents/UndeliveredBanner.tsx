import { Alert, App, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { EdsDocument } from "../../../shared/api/generated/model";
import { sendEdsDocument, waiveEdsDocumentMail } from "../../../shared/api/generated/platform-bff";
import { reasonText } from "./errors";
import { useRefreshDocuments } from "./params";

/**
 * Письмо не ушло адресату (СЦ-1, `ui-standard.md` §14 п. 1, 3, 4): причина и следующий шаг — вверху карточки, а не в
 * журнале внизу. Делопроизводителю — «Отправить ещё раз» и «Вручено иначе»; остальным — у кого следующий шаг. Пока
 * отправка идёт, плашка говорит это и действий не предлагает.
 */
export function UndeliveredBanner({ doc }: { doc: EdsDocument }) {
  const { t } = useTranslation("documents");
  const { message } = App.useApp();
  const { me } = useAuth();
  const refresh = useRefreshDocuments();
  const [busy, setBusy] = useState<"send" | "waive" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const letter = doc.letter;
  if (!letter?.undelivered) return null;
  const last = letter.mailings.at(-1);
  const inProgress = last?.status === "awaiting_pdf" || last?.status === "requested";
  const registrar = canEdit(me, "eds.inbox.register");

  const act = async (kind: "send" | "waive") => {
    setError(null);
    setBusy(kind);
    try {
      if (kind === "send") {
        await sendEdsDocument(doc.id);
        void message.success(t("panel.letter.sendRequested"));
      } else {
        await waiveEdsDocumentMail(doc.id);
        void message.success(t("panel.undelivered.waived"));
      }
      refresh();
    } catch (failure) {
      setError(t("panel.letter.actionFailed", { reason: reasonText(t, failure) }));
    } finally {
      setBusy(null);
    }
  };

  if (inProgress) {
    return <Alert type="info" showIcon message={t("panel.undelivered.inProgress")} />;
  }
  return (
    <Alert
      type="error"
      showIcon
      role="alert"
      message={t("panel.undelivered.title")}
      description={
        <div className="pf-fp-stack" style={{ gap: 8 }}>
          <span>{last?.reason ?? t("panel.undelivered.notTried")}</span>
          {registrar ? (
            <div className="pf-fp-row">
              <Button
                type="primary"
                loading={busy === "send"}
                disabled={busy !== null}
                onClick={() => {
                  void act("send");
                }}
              >
                {t("panel.letter.sendAgain")}
              </Button>
              <Button
                loading={busy === "waive"}
                disabled={busy !== null}
                onClick={() => {
                  void act("waive");
                }}
              >
                {t("panel.undelivered.waive")}
              </Button>
            </div>
          ) : (
            <span className="pf-hint">{t("panel.undelivered.byRegistrar")}</span>
          )}
          {error ? <span role="alert">{error}</span> : null}
        </div>
      }
    />
  );
}
