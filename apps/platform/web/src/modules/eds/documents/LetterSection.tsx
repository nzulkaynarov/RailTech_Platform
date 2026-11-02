import { Alert, App, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type {
  EdsDocument,
  EdsDocumentMailing,
  EdsLetter,
} from "../../../shared/api/generated/model";
import {
  requestEdsDocumentRegistration,
  sendEdsDocument,
  updateEdsDocument,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { History, type HistoryItem } from "../../../shared/ui/History";
import { reasonText } from "./errors";
import { LetterPdfPanel } from "./LetterPdfPanel";
import { useRefreshDocuments } from "./params";

function mailingState(status: EdsDocumentMailing["status"]): HistoryItem["state"] {
  if (status === "sent" || status === "failed") return "done";
  return "waiting";
}

/** Журнал отправки адресату: кому, статус словами (с причиной неудачи), когда. */
function Mailings({ mailings }: { mailings: EdsDocumentMailing[] }) {
  const { t } = useTranslation("documents");
  const { date } = useFormat();
  if (mailings.length === 0) return <p className="pf-fp-sub">{t("panel.letter.noMailings")}</p>;
  const items: HistoryItem[] = mailings.map((mailing) => ({
    state: mailingState(mailing.status),
    title:
      mailing.status === "failed"
        ? mailing.reason
          ? t("panel.letter.mailing.failed", { reason: mailing.reason })
          : t("panel.letter.mailing.failedNoReason")
        : t(`panel.letter.mailing.${mailing.status}`),
    meta: t("panel.letter.mailingMeta", {
      to: mailing.to.join(", "),
      date: date(mailing.finished_at ?? mailing.requested_at, "datetime"),
    }),
  }));
  return <History items={items} label={t("panel.letter.mailings")} />;
}

/** Тело запроса «Зарегистрировать» из сохранённого письма: та же форма целиком, что у «Продолжить». */
function registerBody(doc: EdsDocument, letter: EdsLetter, send: boolean) {
  return {
    subject: doc.subject,
    text: doc.text,
    amount: null,
    due_date: null,
    file_ids: [],
    erp_deal_id: doc.deal?.erp_deal_id ?? null,
    recipient: doc.recipient,
    ...(letter.body
      ? {
          letter: {
            body: letter.body,
            recipient_attention: letter.recipient_attention,
            recipient_email: letter.recipient_email,
            signatory_name: letter.signatory_name,
            signatory_position: letter.signatory_position,
          },
        }
      : {}),
    submit: true,
    ...(send ? { send: true } : {}),
  };
}

/**
 * Письмо на бланке в карточке документа (P4): «кому», почта, подписант, PDF на бланке, журнал отправки адресату и действия —
 * «Передать на регистрацию» (автор без права регистрировать, B-P8B-4), «Зарегистрировать и отправить» (делопроизводитель —
 * черновик, переданный ему), «Отправить адресату ещё раз» (зарегистрированное письмо, например после настройки почты).
 */
export function LetterSection({ doc }: { doc: EdsDocument }) {
  const { t } = useTranslation("documents");
  const { date } = useFormat();
  const { me } = useAuth();
  const { message } = App.useApp();
  const refresh = useRefreshDocuments();
  const [busy, setBusy] = useState<"register" | "handover" | "send" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const letter = doc.letter;
  if (!letter) return null;
  const canRegisterRole = canEdit(me, "eds.inbox.register");
  const email = letter.recipient_email;
  const lastMailing = letter.mailings[letter.mailings.length - 1];
  const mailBusy = lastMailing?.status === "awaiting_pdf" || lastMailing?.status === "requested";
  const canBuild =
    doc.can_edit || doc.can_register === true || (doc.status === "sent" && canRegisterRole);

  const act = async (kind: "register" | "handover" | "send") => {
    setError(null);
    setBusy(kind);
    try {
      if (kind === "register") {
        const result = await updateEdsDocument(doc.id, registerBody(doc, letter, Boolean(email)));
        void message.success(t("panel.letter.registered", { number: result.number ?? "" }));
      } else if (kind === "handover") {
        await requestEdsDocumentRegistration(doc.id);
        void message.success(t("panel.letter.handoverDone"));
      } else {
        await sendEdsDocument(doc.id);
        void message.success(t("panel.letter.sendRequested"));
      }
      refresh();
    } catch (failure) {
      setError(t("panel.letter.actionFailed", { reason: reasonText(t, failure) }));
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <div className="pf-fp-block">
        <h4>{t("panel.letter.title")}</h4>
        <DefinitionList
          items={[
            { label: t("panel.letter.attention"), value: letter.recipient_attention },
            { label: t("panel.letter.email"), value: email },
            {
              label: t("panel.letter.signatory"),
              value:
                letter.signatory_name || letter.signatory_position
                  ? [letter.signatory_position, letter.signatory_name].filter(Boolean).join(" ")
                  : t("panel.letter.signatoryDefault"),
            },
          ]}
        />
        {letter.registration_requested && doc.status === "draft" ? (
          <Alert
            type="info"
            showIcon
            message={t("panel.letter.handedOver", {
              name: letter.registration_requested.by.full_name,
              date: date(letter.registration_requested.at, "datetime"),
            })}
          />
        ) : null}
      </div>
      {letter.body ? (
        <div className="pf-fp-block">
          <LetterPdfPanel
            key={letter.pdf?.requested_at ?? "none"}
            documentId={doc.id}
            initial={letter.pdf}
            canBuild={canBuild}
            subject={doc.subject}
            headingLevel={4}
          />
        </div>
      ) : null}
      <div className="pf-fp-block">
        <h4>{t("panel.letter.mailings")}</h4>
        <Mailings mailings={letter.mailings} />
      </div>
      {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
      <div className="pf-fp-row">
        {doc.can_register ? (
          <Button
            type="primary"
            loading={busy === "register"}
            disabled={busy !== null}
            onClick={() => {
              void act("register");
            }}
          >
            {t(email ? "panel.letter.register" : "panel.letter.registerOnly")}
          </Button>
        ) : null}
        {doc.can_request_registration && !letter.registration_requested ? (
          <Button
            type="primary"
            loading={busy === "handover"}
            disabled={busy !== null}
            onClick={() => {
              void act("handover");
            }}
          >
            {t("panel.letter.handover")}
          </Button>
        ) : null}
        {doc.status === "sent" && canRegisterRole && email && letter.body ? (
          <Button
            loading={busy === "send"}
            disabled={busy !== null || mailBusy}
            onClick={() => {
              void act("send");
            }}
          >
            {t("panel.letter.sendAgain")}
          </Button>
        ) : null}
      </div>
    </>
  );
}
