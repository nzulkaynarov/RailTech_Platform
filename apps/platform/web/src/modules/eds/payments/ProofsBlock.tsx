import { App, Button, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type {
  PaymentCard,
  PaymentProof,
  PaymentProofSource,
} from "../../../shared/api/generated/model";
import {
  getDownloadPaymentProofUrl,
  useAttachPaymentProof,
  useRequestPaymentDoc,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { FileField } from "../../../shared/ui/FileField";
import { ActionToggle, ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { MAX_FILE_BYTES } from "../documents/fileSize";
import { useRefreshPayments } from "./api";

const SOURCES: readonly PaymentProofSource[] = ["EMAIL", "BOT", "CABINET", "MANUAL"];

function attachReason(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 413) return "too_large";
    if (error.status === 415) return "unsupported";
    if (error.status === 409) return "not_open";
    if (error.status === 403) return "forbidden";
    if (error.status >= 500 || error.status === 0) return "unavailable";
    return "unknown";
  }
  return error instanceof TypeError ? "unavailable" : "unknown";
}

/** Платёжки клиента по счёту: файл, откуда пришла, когда, кто приложил; скачать можно любую. */
export function ProofList({ card }: { card: PaymentCard }) {
  const { t } = useTranslation("payments");
  const { date, money } = useFormat();
  if (card.proofs.length === 0) return <p className="pf-hint">{t("proofs.none")}</p>;
  return (
    <ul className="pf-pay-proofs" aria-label={t("proofs.title")}>
      {card.proofs.map((proof: PaymentProof) => (
        <li key={proof.id}>
          <div className="pf-dec-row">
            <a
              className="pf-focusable pf-dec-link"
              href={getDownloadPaymentProofUrl(card.id, proof.id)}
              download
              aria-label={t("proofs.download", { name: proof.original_name })}
            >
              {proof.original_name}
            </a>
            {/* Платёжка без подтверждения у уже оплаченного счёта — лишняя: ждать нечего (отклонение — B-D24-7) */}
            {proof.status === "PENDING" && card.status === "paid" ? (
              <StatusTag kind="proof" status="EXTRA">
                {t("proofs.state.EXTRA")}
              </StatusTag>
            ) : (
              <StatusTag kind="proof" status={proof.status}>
                {t(`proofs.state.${proof.status}`)}
              </StatusTag>
            )}
          </div>
          <span className="pf-hint">
            {t("proofs.from", { source: t(`proofs.source.${proof.source}`) })} ·{" "}
            {t("proofs.received", { date: date(proof.received_at, "datetime") })}
            {proof.recorded_by ? ` · ${t("proofs.byStaff", { name: proof.recorded_by })}` : ""}
          </span>
          {proof.claimed_amount ? (
            <span className="pf-hint">
              {t("proofs.claimed", {
                amount: money(proof.claimed_amount, { currency: card.amount.currency }),
                date: proof.claimed_date ? date(proof.claimed_date) : "—",
              })}
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** «Приложить платёжку»: файл, который пришёл по почте или в бот; из кабинета платёжки придут сами (ERP-04). */
function AttachForm({ card }: { card: PaymentCard }) {
  const { t } = useTranslation("payments");
  const { message } = App.useApp();
  const refresh = useRefreshPayments();
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;
  const [files, setFiles] = useState<File[]>([]);
  const [source, setSource] = useState<PaymentProofSource>("EMAIL");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const attach = useAttachPaymentProof({
    mutation: {
      onSuccess: () => {
        void message.success(t("attach.done"));
        void refresh();
        setFiles([]);
        setNote("");
        setError(null);
      },
      onError: (failure) => {
        const reason = attachReason(failure);
        setError(t("attach.failed", { reason: t(`attach.reasons.${reason}`) }));
        if (reason === "not_open") void refresh();
      },
    },
  });

  const submit = () => {
    const file = files[0];
    if (!file) {
      setError(t("attach.needFile"));
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError(t("attach.failed", { reason: t("attach.reasons.too_large") }));
      return;
    }
    setError(null);
    attach.mutate({
      id: card.id,
      data: { file, source, ...(note.trim() ? { note: note.trim() } : {}) },
    });
  };

  return (
    <form
      className="pf-pay-form"
      aria-label={t("attach.form")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <FormField id={id("file")} label={t("attach.file.label")} hint={t("attach.file.hint")}>
        <FileField
          id={id("file")}
          value={files}
          aria-describedby={`${id("file")}-hint`}
          onChange={(next) => {
            setFiles(next);
            setError(null);
          }}
        />
      </FormField>
      <FormField id={id("source")} label={t("attach.source.label")}>
        <Select
          id={id("source")}
          value={source}
          options={SOURCES.map((value) => ({ value, label: t(`proofs.source.${value}`) }))}
          onChange={(value: PaymentProofSource) => {
            setSource(value);
          }}
        />
      </FormField>
      <FormField id={id("note")} label={t("attach.note.label")} hint={t("attach.note.hint")}>
        <input
          id={id("note")}
          className="ant-input"
          value={note}
          maxLength={500}
          aria-describedby={`${id("note")}-hint`}
          onChange={(event) => {
            setNote(event.target.value);
          }}
        />
      </FormField>
      <ErrorNote message={error} />
      <Button htmlType="submit" loading={attach.isPending}>
        {t("attach.submit")}
      </Button>
    </form>
  );
}

/** «Запросить платёжку»: шаблон сообщения клиенту и отметка в журнале счёта (автоотправки нет — хвост B-D24-1). */
function RequestForm({ card }: { card: PaymentCard }) {
  const { t } = useTranslation("payments");
  const { date, money } = useFormat();
  const { message } = App.useApp();
  const refresh = useRefreshPayments();
  const ids = useId();
  const [error, setError] = useState<string | null>(null);
  const amount = money(card.balance.amount, { currency: card.balance.currency });
  const text = card.due_date
    ? t("request.template", { number: card.number, amount, due: date(card.due_date) })
    : t("request.templateNoDue", { number: card.number, amount });
  const mark = useRequestPaymentDoc({
    mutation: {
      onSuccess: () => {
        void message.success(t("request.done"));
        void refresh();
        setError(null);
      },
      onError: (failure) => {
        setError(
          t("request.failed", {
            reason: t(`attach.reasons.${attachReason(failure)}`),
          }),
        );
      },
    },
  });
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      void message.success(t("request.copied"));
    } catch {
      void message.warning(t("request.copyFailed"));
    }
  };
  return (
    <div className="pf-pay-form">
      <FormField id={`${ids}-text`} label={t("request.label")}>
        <textarea
          id={`${ids}-text`}
          className="pf-pay-message"
          readOnly
          value={text}
          aria-describedby={`${ids}-note`}
        />
      </FormField>
      <p className="pf-hint" id={`${ids}-note`}>
        {t("request.note")}
      </p>
      <ErrorNote message={error} />
      <div className="pf-dec-row">
        <Button
          onClick={() => {
            void copy();
          }}
        >
          {t("request.copy")}
        </Button>
        <Button
          loading={mark.isPending}
          onClick={() => {
            mark.mutate({ id: card.id });
          }}
        >
          {t("request.mark")}
        </Button>
      </div>
    </div>
  );
}

/** Платёжки клиента со вторичными действиями: приложить файл и запросить платёжку у клиента. */
export function ProofsBlock({ card }: { card: PaymentCard }) {
  const { t } = useTranslation("payments");
  const { date } = useFormat();
  const [attach, setAttach] = useState(false);
  const [request, setRequest] = useState(false);
  return (
    <section className="pf-dec-page" aria-label={t("proofs.title")}>
      <h4 className="pf-dec-subhead">{t("proofs.title")}</h4>
      <ProofList card={card} />
      {card.payment_doc_requested_at ? (
        <p className="pf-hint">
          {t("request.requestedAt", { date: date(card.payment_doc_requested_at, "datetime") })}
        </p>
      ) : null}
      {card.can_attach_proof ? (
        <ActionToggle label={t("attach.toggle")} open={attach} onToggle={setAttach}>
          <AttachForm card={card} />
        </ActionToggle>
      ) : null}
      {card.can_request_proof ? (
        <ActionToggle label={t("request.toggle")} open={request} onToggle={setRequest}>
          <RequestForm card={card} />
        </ActionToggle>
      ) : null}
    </section>
  );
}
