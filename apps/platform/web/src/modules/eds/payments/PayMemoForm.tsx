import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Button, Input } from "antd";
import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PaymentMemoCard } from "../../../shared/api/generated/model";
import {
  decideMemoApproval,
  getListMemoApprovalsQueryKey,
  payPaymentMemo,
  uploadPaymentReceiptFile,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { DateField } from "../../../shared/ui/DateField";
import { FileField } from "../../../shared/ui/FileField";
import { ActionToggle, ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { companyDate } from "../inbox/api";
import { MAX_FILE_BYTES } from "../documents/fileSize";
import { type MemoReason, isMemoStale, memoReason, useRefreshPayments } from "./api";
import { normalizeAmount, toCents } from "./model";

export interface PayMemoFormProps {
  memo: PaymentMemoCard;
  variant?: "panel" | "sheet";
  onDone?: () => void;
}

/**
 * «Оплачено» для служебки к оплате (SPEC-v3 §3.2 п. 5): дата платежа, сумма (не больше согласованной), платёжка и заметка;
 * главная кнопка с блоком «Что произойдёт». Платёжка загружается в EDS перед оплатой и привязывается к записке; если оплата
 * отклонена, файл остаётся загруженным и повторно не грузится. «Вернуть автору» — вторичное действие с обязательной причиной.
 */
export function PayMemoForm({ memo, variant = "panel", onDone }: PayMemoFormProps) {
  const { t } = useTranslation("payments");
  const { message } = App.useApp();
  const { money } = useFormat();
  const refresh = useRefreshPayments();
  const client = useQueryClient();
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;
  const approved = memo.amount?.amount ?? "0.00";
  const currency = memo.amount?.currency ?? "UZS";
  const today = companyDate();
  const [receiptFiles, setReceiptFiles] = useState<File[]>([]);
  const uploaded = useRef<{ key: string; id: string } | null>(null);

  const [date, setDate] = useState(today);
  const [amount, setAmount] = useState(approved);
  const [note, setNote] = useState("");
  const [failure, setFailure] = useState<{ reason: MemoReason } | null>(null);
  const [returning, setReturning] = useState(false);
  const [reason, setReason] = useState("");
  const [returnError, setReturnError] = useState<string | null>(null);

  const normalized = normalizeAmount(amount);
  const dateValid = date !== "" && date <= today;
  const overApproved = normalized !== null && toCents(normalized) > toCents(approved);
  const invalid =
    normalized === null || overApproved ? "invalidAmount" : !dateValid ? "invalidDate" : null;
  const fmt = (value: string) => money(value, { currency });

  const pay = useMutation({
    mutationFn: async () => {
      let receipt: string | null = null;
      const file = receiptFiles[0];
      if (file) {
        if (file.size > MAX_FILE_BYTES) throw new Error("too_large");
        const signature = `${file.name}:${String(file.size)}:${String(file.lastModified)}`;
        if (uploaded.current?.key !== signature) {
          const stored = await uploadPaymentReceiptFile({ file });
          uploaded.current = { key: signature, id: stored.id };
        }
        receipt = uploaded.current.id;
      }
      return payPaymentMemo(memo.id, {
        paid_on: date,
        amount: normalized ?? "",
        currency,
        ...(receipt ? { receipt_file_id: receipt } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      });
    },
    onSuccess: () => {
      setFailure(null);
      void refresh();
      void message.success(t("memo.form.done", { number: memo.number ?? "" }));
      onDone?.();
    },
    onError: (error) => {
      const code = memoReason(error);
      if (isMemoStale(code)) void refresh();
      setFailure({ reason: code });
    },
  });

  const giveBack = useMutation({
    mutationFn: () =>
      decideMemoApproval(memo.approval_id ?? "", { decision: "return", comment: reason.trim() }),
    onSuccess: () => {
      setReturnError(null);
      void refresh();
      void client.invalidateQueries({ queryKey: getListMemoApprovalsQueryKey() });
      void message.success(t("memo.form.return.done"));
      onDone?.();
    },
    onError: (error) => {
      const code = memoReason(error);
      if (isMemoStale(code)) void refresh();
      setReturnError(t("memo.form.return.failed", { reason: t(`memo.form.reasons.${code}`) }));
    },
  });

  const failureText = failure
    ? t("memo.form.failed", {
        reason:
          pay.error instanceof Error && pay.error.message === "too_large"
            ? t("attach.reasons.too_large")
            : t(`memo.form.reasons.${failure.reason}`),
      })
    : null;

  return (
    <form
      className={`pf-dec pf-dec--${variant}`}
      aria-label={t("memo.form.name")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!invalid && !pay.isPending) {
          setFailure(null);
          pay.mutate();
        }
      }}
    >
      <FormField id={id("date")} label={t("memo.form.date.label")} hint={t("memo.form.date.hint")}>
        <DateField
          id={id("date")}
          value={date}
          max={today}
          aria-describedby={`${id("date")}-hint`}
          aria-invalid={!dateValid}
          onChange={(next) => {
            setDate(next);
            setFailure(null);
          }}
        />
      </FormField>
      <FormField
        id={id("amount")}
        label={t("memo.form.amount.label", { currency })}
        hint={t("memo.form.amount.hint", { approved: fmt(approved) })}
      >
        <Input
          id={id("amount")}
          value={amount}
          inputMode="decimal"
          autoComplete="off"
          aria-describedby={`${id("amount")}-hint`}
          aria-invalid={normalized === null || overApproved}
          onChange={(event) => {
            setAmount(event.target.value);
            setFailure(null);
          }}
        />
      </FormField>
      <FormField
        id={id("receipt")}
        label={t("memo.form.receipt.label")}
        hint={t("memo.form.receipt.hint")}
      >
        <FileField
          id={id("receipt")}
          value={receiptFiles}
          aria-describedby={`${id("receipt")}-hint`}
          onChange={(files) => {
            setReceiptFiles(files);
            setFailure(null);
          }}
        />
      </FormField>
      <FormField id={id("note")} label={t("memo.form.note.label")} hint={t("memo.form.note.hint")}>
        <Input
          id={id("note")}
          value={note}
          maxLength={500}
          aria-describedby={`${id("note")}-hint`}
          onChange={(event) => {
            setNote(event.target.value);
          }}
        />
      </FormField>

      <Consequence
        items={[
          t("memo.form.consequence.step1", {
            number: memo.number ?? "",
            amount: fmt(normalized ?? approved),
            date: date || today,
          }),
          t("memo.form.consequence.step2"),
          t("memo.form.consequence.step3"),
        ]}
      />

      <ErrorNote message={failureText} />

      <div className="pf-dec-actions">
        <Button
          type="primary"
          htmlType="submit"
          block
          loading={pay.isPending}
          disabled={invalid !== null || pay.isPending}
          aria-describedby={invalid ? id("invalid") : undefined}
        >
          {t("memo.form.submit")}
        </Button>
        {invalid ? (
          <p className="pf-hint" id={id("invalid")}>
            {t(`memo.form.${invalid}`)}
          </p>
        ) : null}
        {memo.can_return && memo.approval_id ? (
          <ActionToggle
            label={t("memo.form.return.toggle")}
            open={returning}
            onToggle={setReturning}
            danger
          >
            <div className="pf-pay-form">
              <FormField
                id={id("reason")}
                label={t("memo.form.return.label")}
                hint={t("memo.form.return.hint")}
              >
                <Input.TextArea
                  id={id("reason")}
                  value={reason}
                  maxLength={4000}
                  autoSize={{ minRows: 2, maxRows: 6 }}
                  aria-describedby={`${id("reason")}-hint`}
                  onChange={(event) => {
                    setReason(event.target.value);
                    setReturnError(null);
                  }}
                />
              </FormField>
              <ErrorNote message={returnError} />
              <Button
                danger
                loading={giveBack.isPending}
                disabled={reason.trim() === "" || giveBack.isPending}
                onClick={() => {
                  giveBack.mutate();
                }}
              >
                {t("memo.form.return.submit")}
              </Button>
            </div>
          </ActionToggle>
        ) : null}
      </div>
    </form>
  );
}
