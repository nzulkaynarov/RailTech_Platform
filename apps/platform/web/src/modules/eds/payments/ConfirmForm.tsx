import { useMutation } from "@tanstack/react-query";
import { App, Button, Input } from "antd";
import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { PaymentCard } from "../../../shared/api/generated/model";
import { confirmPayment } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { DateField } from "../../../shared/ui/DateField";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { companyDate } from "../inbox/api";
import { type InvoiceReason, invoiceReason, isStale, useRefreshPayments } from "./api";
import { newKey, normalizeAmount, remainderAfter, toCents } from "./model";

export interface ConfirmFormProps {
  card: PaymentCard;
  /** Лист на телефоне: кнопки закреплены внизу */
  variant?: "panel" | "sheet";
  /** Оплата подтверждена (лист закрывается) */
  onDone?: () => void;
}

/**
 * «Подтвердить оплату» (SPEC-v3 §3.1 шаг 8): сумма и дата — по выписке банка, платёжка клиента — по желанию, номер операции
 * банка — необязательно. Сумма меньше остатка — частичная оплата: кнопка и блок «Что произойдёт» меняют слова, остаток виден.
 * Повтор безопасен: ключ повтора живёт, пока поля не изменены (ERP отдаёт прежний ответ), тот же `proof_id` и тот же номер
 * операции платёж не дублируют. Сумму больше остатка не принимает ERP — ответ словами, введённое остаётся.
 */
export function ConfirmForm({ card, variant = "panel", onDone }: ConfirmFormProps) {
  const { t } = useTranslation("payments");
  const { message } = App.useApp();
  const { money } = useFormat();
  const refresh = useRefreshPayments();
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;
  const amountRef = useRef<HTMLInputElement | null>(null);

  const pending = card.proofs.filter((p) => p.status === "PENDING");
  const today = companyDate();
  const [amount, setAmount] = useState(card.balance.amount);
  const [date, setDate] = useState(today);
  const [reference, setReference] = useState("");
  const [proofId, setProofId] = useState<number | null>(pending[0]?.id ?? null);
  const [partialMode, setPartialMode] = useState(false);
  const [failure, setFailure] = useState<{ reason: InvoiceReason } | null>(null);
  const key = useRef<{ signature: string; value: string } | null>(null);

  const normalized = normalizeAmount(amount);
  const dateValid = date !== "" && date <= today;
  const partial = normalized !== null && toCents(normalized) < toCents(card.balance.amount);
  const currency = card.balance.currency;
  const fmt = (value: string) => money(value, { currency });
  const rest = normalized ? remainderAfter(card, normalized) : card.balance.amount;
  const invalid = normalized === null ? "invalidAmount" : !dateValid ? "invalidDate" : null;

  const confirm = useMutation({
    mutationFn: (variables: { apiKey: string }) =>
      confirmPayment(
        card.id,
        {
          amount: normalized ?? "",
          date,
          ...(reference.trim() ? { reference: reference.trim() } : {}),
          ...(proofId !== null ? { proof_id: proofId } : {}),
        },
        { headers: { "Idempotency-Key": variables.apiKey } },
      ),
    onSuccess: (result) => {
      key.current = null;
      setFailure(null);
      setPartialMode(false);
      void refresh();
      if (result.replayed) void message.info(t("confirm.replayed"));
      else if (partial) {
        void message.success(
          t("confirm.donePartial", { amount: fmt(normalized), rest: fmt(result.balance.amount) }),
        );
      } else void message.success(t("confirm.done", { amount: fmt(normalized ?? "") }));
      onDone?.();
    },
    onError: (error) => {
      const reason = invoiceReason(error);
      // Карточка устарела (оплачен, отменён, платёжка исчезла): введённое бесполезно, данные обновляем.
      if (isStale(reason)) void refresh();
      setFailure({ reason });
    },
  });

  const send = () => {
    if (invalid || confirm.isPending) return;
    const signature = JSON.stringify([normalized, date, reference.trim(), proofId]);
    if (key.current?.signature !== signature) key.current = { signature, value: newKey() };
    setFailure(null);
    confirm.mutate({ apiKey: key.current.value });
  };

  const forget = () => {
    key.current = null;
    setFailure(null);
  };
  const failureText = failure
    ? t("confirm.failed", {
        reason: t(`confirm.reasons.${failure.reason}`, { balance: fmt(card.balance.amount) }),
      })
    : null;

  const items = partial
    ? [
        t("confirm.consequence.partial.step1", {
          number: card.number,
          amount: fmt(normalized),
          rest: fmt(rest),
        }),
        t("confirm.consequence.partial.step2"),
        t("confirm.consequence.partial.step3"),
      ]
    : [
        t("confirm.consequence.full.step1", {
          number: card.number,
          amount: fmt(normalized ?? card.balance.amount),
        }),
        t("confirm.consequence.full.step2", { project: card.project_number }),
        t("confirm.consequence.full.step3"),
      ];

  return (
    <form
      className={`pf-dec pf-dec--${variant}`}
      aria-label={t("confirm.name")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      {pending.length > 0 ? (
        <fieldset className="pf-pay-radio">
          <legend>{t("confirm.proof.label")}</legend>
          {pending.map((proof) => (
            <label key={proof.id}>
              <input
                type="radio"
                name={id("proof")}
                checked={proofId === proof.id}
                onChange={() => {
                  setProofId(proof.id);
                  forget();
                }}
              />
              <span>{proof.original_name}</span>
            </label>
          ))}
          <label>
            <input
              type="radio"
              name={id("proof")}
              checked={proofId === null}
              onChange={() => {
                setProofId(null);
                forget();
              }}
            />
            <span>{t("confirm.proof.none")}</span>
          </label>
        </fieldset>
      ) : null}

      <FormField
        id={id("amount")}
        label={t("confirm.amount.label")}
        hint={
          partial || partialMode
            ? t("confirm.partialHint")
            : t("confirm.amount.hint", { balance: fmt(card.balance.amount) })
        }
      >
        <Input
          id={id("amount")}
          ref={(node) => {
            amountRef.current = node?.input ?? null;
          }}
          value={amount}
          inputMode="decimal"
          autoComplete="off"
          suffix={currency}
          aria-describedby={`${id("amount")}-hint`}
          aria-invalid={normalized === null}
          onChange={(event) => {
            setAmount(event.target.value);
            forget();
          }}
        />
      </FormField>
      <FormField id={id("date")} label={t("confirm.date.label")} hint={t("confirm.date.hint")}>
        <DateField
          id={id("date")}
          value={date}
          max={today}
          aria-describedby={`${id("date")}-hint`}
          aria-invalid={!dateValid}
          onChange={(next) => {
            setDate(next);
            forget();
          }}
        />
      </FormField>
      <FormField
        id={id("reference")}
        label={t("confirm.reference.label")}
        hint={t("confirm.reference.hint")}
      >
        <Input
          id={id("reference")}
          value={reference}
          maxLength={255}
          autoComplete="off"
          aria-describedby={`${id("reference")}-hint`}
          onChange={(event) => {
            setReference(event.target.value);
            forget();
          }}
        />
      </FormField>

      <Consequence items={items} />

      <ErrorNote message={failureText} />

      <div className="pf-dec-actions">
        <Button
          type="primary"
          htmlType="submit"
          block
          loading={confirm.isPending}
          disabled={invalid !== null || confirm.isPending}
          aria-describedby={invalid ? id("invalid") : undefined}
        >
          {partial ? t("confirm.submitPartial") : t("confirm.submit")}
        </Button>
        <div className="pf-dec-secondary">
          <Button
            block
            disabled={confirm.isPending}
            onClick={() => {
              setAmount("");
              setPartialMode(true);
              forget();
              amountRef.current?.focus();
            }}
          >
            {t("confirm.partial")}
          </Button>
        </div>
        {invalid ? (
          <p className="pf-hint" id={id("invalid")}>
            {t(`confirm.${invalid}`)}
          </p>
        ) : null}
      </div>
    </form>
  );
}
