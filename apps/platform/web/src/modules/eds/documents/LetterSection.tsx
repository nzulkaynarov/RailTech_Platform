import { Alert, App, Button, Checkbox, Radio, Space } from "antd";
import { Dialog } from "../../../shared/ui/Dialog";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type {
  EdsDocument,
  EdsDocumentMailing,
  EdsDocumentSignInDispatchMethod,
  EdsLetter,
  EdsSigningHint,
} from "../../../shared/api/generated/model";
import {
  changeEdsDocumentSigner,
  remindEdsDocumentSigner,
  requestEdsDocumentRegistration,
  sendEdsDocument,
  signEdsDocument,
  updateEdsDocument,
  useListEdsSigners,
  withdrawEdsDocumentFromSigning,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList, type DefinitionItem } from "../../../shared/ui/DefinitionList";
import { EmployeePicker } from "../../../shared/ui/EmployeePicker";
import { History, type HistoryItem } from "../../../shared/ui/History";
import { reasonText } from "./errors";
import { LetterPdfPanel } from "./LetterPdfPanel";
import { useRefreshDocuments } from "./params";

function mailingState(status: EdsDocumentMailing["status"]): HistoryItem["state"] {
  if (status === "sent") return "done";
  if (status === "failed") return "failed"; // у неудачи — красный крестик, не зелёная галочка (СЦ-1)
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
    // адресат ссылкой (СУЩ-2.6); письмо до него без ссылки адресата не передаёт — регистрация ждёт сопоставления
    ...(doc.recipient?.company_id
      ? {
          recipient: {
            company_id: doc.recipient.company_id,
            contact_id: doc.recipient.contact_id,
          },
        }
      : {}),
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
 * Вместо «Подписать», когда EDS не разрешает (СЦ-9, ГЛ-0): причина отказа целым предложением с именем того, кто подпишет;
 * подписать некому — куда идти за полномочием.
 */
function SignerHint({ hint }: { hint: EdsSigningHint }) {
  const { t } = useTranslation("documents");
  const { me } = useAuth();
  if (hint.signer) {
    const reasonKey = `panel.letter.refusal.${hint.reason ?? "none"}`;
    const known = hint.reason ? t(reasonKey, { defaultValue: "" }) : "";
    return (
      <span className="pf-fp-sub" role="status">
        {known
          ? t(reasonKey, { name: hint.signer.full_name })
          : t("panel.letter.signer", { name: hint.signer.full_name })}
      </span>
    );
  }
  return (
    <span className="pf-fp-sub">
      {t("panel.letter.noSigner")}
      {canEdit(me, "eds.signing.manage") ? (
        <>
          {": "}
          <Link to="/admin/signing" style={{ textDecoration: "underline" }}>
            {t("panel.letter.noSignerLink")}
          </Link>
        </>
      ) : null}
    </span>
  );
}

/** «На подписи у <ФИО>, <должность> с <даты>» — подписант и срок (ГЛ-0); подписывает сам спросивший — «Подписываете вы». */
function OnSigning({ doc, letter }: { doc: EdsDocument; letter: EdsLetter }) {
  const { t } = useTranslation("documents");
  const { date } = useFormat();
  const request = letter.registration_requested;
  if (!request || !doc.awaiting_signature) return null;
  const hint = doc.signing_hint;
  const since = date(request.at, "datetime");
  let text: string;
  if (!hint?.signer) {
    text = t("panel.letter.handedOver", { name: request.by.full_name, date: since });
  } else if (hint.signer_is_you) {
    text = t("panel.letter.youSign", { date: since });
  } else {
    const who = [hint.signer.full_name, hint.signer_position].filter(Boolean).join(", ");
    text = t("panel.letter.onSigning", { who, date: since });
  }
  return <Alert type="info" showIcon message={text} />;
}

/**
 * Письмо на бланке в карточке документа (P4): «кому», почта, подписант, PDF на бланке, журнал отправки адресату и действия —
 * «Передать на подпись» (автор без права регистрировать, B-P8B-4), «Зарегистрировать и отправить» (делопроизводитель —
 * черновик, переданный ему), «Отправить адресату ещё раз» (зарегистрированное письмо, например после настройки почты).
 */
export function LetterSection({ doc }: { doc: EdsDocument }) {
  const { t } = useTranslation("documents");
  const { date } = useFormat();
  const { me } = useAuth();
  const { message } = App.useApp();
  const refresh = useRefreshDocuments();
  const [busy, setBusy] = useState<
    "register" | "handover" | "send" | "sign" | "remind" | "withdraw" | "signer" | null
  >(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickedSigner, setPickedSigner] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [signModalOpen, setSignModalOpen] = useState(false);
  const [dispatchMethod, setDispatchMethod] = useState<EdsDocumentSignInDispatchMethod>(
    doc.letter?.recipient_email ? "email" : "paper",
  );
  const [sendEmail, setSendEmail] = useState(Boolean(doc.letter?.recipient_email));
  const signersQuery = useListEdsSigners({ query: { enabled: pickerOpen, staleTime: 60_000 } });
  const letter = doc.letter;
  if (!letter) return null;
  const canRegisterRole = canEdit(me, "eds.inbox.register");
  const email = letter.recipient_email;
  const lastMailing = letter.mailings[letter.mailings.length - 1];
  const mailBusy = lastMailing?.status === "awaiting_pdf" || lastMailing?.status === "requested";
  const canBuild =
    doc.can_edit || doc.can_register === true || (doc.status === "sent" && canRegisterRole);

  const handleSign = async () => {
    setError(null);
    setBusy("sign");
    try {
      const result = await signEdsDocument(doc.id, {
        dispatch_method: dispatchMethod,
        send: dispatchMethod === "email" ? sendEmail : false,
      });
      void message.success(t("panel.letter.signed", { number: result.number ?? "" }));
      setSignModalOpen(false);
      refresh();
    } catch (failure) {
      setError(t("panel.letter.actionFailed", { reason: reasonText(t, failure) }));
    } finally {
      setBusy(null);
    }
  };

  /** «Напомнить», «Отозвать», «Сменить подписанта» над письмом на подписи (ГЛ-0): автор, без подтверждений — всё обратимо. */
  const manage = async (kind: "remind" | "withdraw" | "signer") => {
    setError(null);
    setBusy(kind);
    try {
      if (kind === "remind") {
        await remindEdsDocumentSigner(doc.id);
        void message.success(
          t("panel.letter.reminded", { name: doc.signing_hint?.signer?.full_name ?? "" }),
        );
      } else if (kind === "withdraw") {
        await withdrawEdsDocumentFromSigning(doc.id);
        void message.success(t("panel.letter.withdrawn"));
      } else {
        const id = pickedSigner ? Number(pickedSigner) : null;
        await changeEdsDocumentSigner(doc.id, { signer_crm_user_id: id });
        setPickerOpen(false);
        void message.success(t("panel.letter.signerChanged"));
      }
      refresh();
    } catch (failure) {
      setError(t("panel.letter.actionFailed", { reason: reasonText(t, failure) }));
    } finally {
      setBusy(null);
    }
  };

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

  // Адресат текстом из писем до СУЩ-2.6: пока его не выбрали из контрагентов, письмо не регистрируется
  const unmatched = doc.status !== "sent" && Boolean(doc.recipient) && !doc.recipient?.company_id;
  const definitionItems: DefinitionItem[] = [
    { label: t("panel.letter.attention"), value: letter.recipient_attention },
    { label: t("panel.letter.email"), value: email },
    {
      label: t("panel.letter.signatory"),
      value:
        letter.signatory_name || letter.signatory_position
          ? [letter.signatory_position, letter.signatory_name].filter(Boolean).join(" ")
          : t("panel.letter.signatoryDefault"),
    },
  ];

  if (doc.signed_at) {
    definitionItems.push({
      label: t("panel.letter.signedBy"),
      value: doc.acting_for
        ? `${doc.signed_by?.full_name ?? ""} (${t("panel.letter.actingFor", { name: doc.acting_for.full_name })})`
        : doc.signed_by?.full_name,
    });
    if (doc.signatory_basis_text) {
      definitionItems.push({
        label: t("panel.letter.signatoryBasis"),
        value: doc.signatory_basis_text,
      });
    }
    definitionItems.push({
      label: t("panel.letter.signedAt"),
      value: date(doc.signed_at, "datetime"),
    });
    if (doc.verification_code) {
      definitionItems.push({
        label: t("panel.letter.verificationCode"),
        value: doc.verification_url ? (
          <a
            href={doc.verification_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontFamily: "monospace" }}
          >
            {doc.verification_code}
          </a>
        ) : (
          <span style={{ fontFamily: "monospace" }}>{doc.verification_code}</span>
        ),
      });
    }
    if (doc.dispatch_method) {
      definitionItems.push({
        label: t("panel.letter.dispatchMethodLabel"),
        value: t(`panel.letter.dispatchMethods.${doc.dispatch_method}`, {
          defaultValue: doc.dispatch_method,
        }),
      });
    }
  }

  return (
    <>
      <div className="pf-fp-block">
        <h4>{t("panel.letter.title")}</h4>
        <DefinitionList items={definitionItems} />
        {unmatched ? <Alert type="warning" showIcon message={t("panel.letter.unmatched")} /> : null}
        <OnSigning doc={doc} letter={letter} />
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
        {doc.can_sign ? (
          <Button
            type="primary"
            loading={busy === "sign"}
            disabled={busy !== null}
            onClick={() => {
              setSignModalOpen(true);
            }}
          >
            {t(
              doc.can_manage_handover && doc.signing_hint && !doc.signing_hint.signer_is_you
                ? "panel.letter.signSelf"
                : "panel.letter.sign",
            )}
          </Button>
        ) : null}
        {!doc.can_sign && doc.signing_hint ? <SignerHint hint={doc.signing_hint} /> : null}
        {doc.can_manage_handover ? (
          <>
            <Button
              loading={busy === "remind"}
              disabled={busy !== null || doc.signing_hint?.signer_is_you === true}
              onClick={() => {
                void manage("remind");
              }}
            >
              {t("panel.letter.remind")}
            </Button>
            <Button
              loading={busy === "withdraw"}
              disabled={busy !== null}
              onClick={() => {
                void manage("withdraw");
              }}
            >
              {t("panel.letter.withdraw")}
            </Button>
            <Button
              disabled={busy !== null}
              onClick={() => {
                setPickedSigner(
                  letter.signer_crm_user_id ? String(letter.signer_crm_user_id) : undefined,
                );
                setPickerOpen(true);
              }}
            >
              {t("panel.letter.changeSigner")}
            </Button>
          </>
        ) : null}
        {doc.can_register && !doc.can_sign ? (
          <Button
            type="primary"
            loading={busy === "register"}
            disabled={busy !== null || unmatched}
            onClick={() => {
              void act("register");
            }}
          >
            {t(email ? "panel.letter.register" : "panel.letter.registerOnly")}
          </Button>
        ) : null}
        {doc.can_request_registration && !letter.registration_requested && !doc.can_sign ? (
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
        {/* Недоставленному письму «Отправить ещё раз» — в плашке вверху карточки (СЦ-1); здесь — повтор доставленного */}
        {doc.status === "sent" && canRegisterRole && email && letter.body && !letter.undelivered ? (
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

      <Dialog
        open={pickerOpen}
        onCancel={() => {
          if (busy !== "signer") setPickerOpen(false);
        }}
        title={t("panel.letter.changeSignerTitle")}
        footer={[
          <Button
            key="cancel"
            disabled={busy === "signer"}
            onClick={() => {
              setPickerOpen(false);
            }}
          >
            {t("panel.letter.cancel")}
          </Button>,
          <Button
            key="save"
            type="primary"
            loading={busy === "signer"}
            disabled={!pickedSigner}
            onClick={() => {
              void manage("signer");
            }}
          >
            {t("panel.letter.changeSignerSave")}
          </Button>,
        ]}
      >
        <EmployeePicker
          id="pf-change-signer"
          value={pickedSigner}
          options={signersQuery.data?.items ?? []}
          loading={signersQuery.isPending}
          allowClear={false}
          placeholder={t("panel.letter.changeSignerPlaceholder")}
          emptyText={t("panel.letter.noSigner")}
          onChange={setPickedSigner}
        />
      </Dialog>

      <Dialog
        open={signModalOpen}
        onCancel={() => {
          if (busy !== "sign") setSignModalOpen(false);
        }}
        title={t("panel.letter.signModalTitle")}
        footer={[
          <Button
            key="cancel"
            disabled={busy === "sign"}
            onClick={() => {
              setSignModalOpen(false);
            }}
          >
            {t("panel.letter.cancel")}
          </Button>,
          <Button
            key="sign"
            type="primary"
            loading={busy === "sign"}
            onClick={() => {
              void handleSign();
            }}
          >
            {t("panel.letter.confirmSign")}
          </Button>,
        ]}
      >
        <p className="pf-fp-sub" style={{ marginBottom: 16 }}>
          {t("panel.letter.signModalDesc")}
        </p>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", marginBottom: 8, fontWeight: 500 }}>
            {t("panel.letter.dispatchMethod")}
          </label>
          <Radio.Group
            value={dispatchMethod}
            onChange={(e) => {
              const val = e.target.value as EdsDocumentSignInDispatchMethod;
              setDispatchMethod(val);
              if (val === "email") {
                setSendEmail(Boolean(email));
              }
            }}
          >
            <Space direction="vertical">
              <Radio value="email" disabled={!email}>
                {t("panel.letter.dispatchMethods.email")}
                {!email ? ` (${t("panel.letter.noEmailWarning")})` : ""}
              </Radio>
              <Radio value="paper">{t("panel.letter.dispatchMethods.paper")}</Radio>
              <Radio value="courier">{t("panel.letter.dispatchMethods.courier")}</Radio>
              <Radio value="edo">{t("panel.letter.dispatchMethods.edo")}</Radio>
              <Radio value="other">{t("panel.letter.dispatchMethods.other")}</Radio>
            </Space>
          </Radio.Group>
        </div>
        {dispatchMethod === "email" && email ? (
          <div style={{ marginTop: 8 }}>
            <Checkbox
              checked={sendEmail}
              onChange={(e) => {
                setSendEmail(e.target.checked);
              }}
            >
              {t("panel.letter.sendImmediately")}
            </Checkbox>
          </div>
        ) : null}
      </Dialog>
    </>
  );
}
