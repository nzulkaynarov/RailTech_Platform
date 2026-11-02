import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { PaymentCard } from "../../../shared/api/generated/model";
import { getGetPaymentQueryKey, issuePayment } from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { errorReason, useRefreshPayments } from "./api";
import { BankDetailsNotice } from "./BankDetailsNotice";

/** Причины отказа «Выставить счёт» словарным ключом (`payments:issue.reasons.*`). */
type IssueReason =
  | "already_issued"
  | "bank_details_required"
  | "forbidden"
  | "not_found"
  | "unavailable"
  | "unknown";

function issueReason(error: unknown): IssueReason {
  if (error instanceof ApiError) {
    const reason = errorReason(error);
    if (reason === "already_issued" || reason === "bank_details_required") return reason;
    if (error.status === 403) return "forbidden";
    if (error.status === 404) return "not_found";
    if (error.status >= 500 || error.status === 0) return "unavailable";
    return "unknown";
  }
  return error instanceof TypeError ? "unavailable" : "unknown";
}

/**
 * «Выставить счёт» (B-D24-4, SPEC-v3 §3.1 шаг 7): черновик счёта → «Выставлен». Блок «Что произойдёт» — правда о том, что
 * делает ERP при выставлении: дата и срок оплаты, реквизиты и PDF, кабинет клиента, сообщение бота и письмо. Право решает ERP
 * (`finance.invoice`); без реквизитов компании ERP откажет — это видно заранее (`bank_details_ready`, D26G-6): плашка
 * «кто и где заполняет» и неактивная кнопка; отказ ERP после клика (реквизиты стёрли между чтением и кликом) — словами.
 */
export function IssueForm({
  card,
  variant = "panel",
  onDone,
}: {
  card: PaymentCard;
  variant?: "panel" | "sheet";
  onDone?: (() => void) | undefined;
}) {
  const { t } = useTranslation("payments");
  const { message } = App.useApp();
  const client = useQueryClient();
  const refresh = useRefreshPayments();
  const [failure, setFailure] = useState<IssueReason | null>(null);
  const issue = useMutation({
    mutationFn: () => issuePayment(card.id),
    onSuccess: (next) => {
      setFailure(null);
      client.setQueryData(getGetPaymentQueryKey(card.id), next);
      void refresh();
      void message.success(t("issue.done", { number: next.number }));
      onDone?.();
    },
    onError: (error) => {
      const reason = issueReason(error);
      if (reason === "already_issued") void refresh();
      setFailure(reason);
    },
  });
  const noBank = !card.bank_details_ready;
  return (
    <form
      className={`pf-dec pf-dec--${variant}`}
      aria-label={t("issue.name")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!issue.isPending && !noBank) issue.mutate();
      }}
    >
      <p className="pf-hint">{t("issue.lead", { number: card.number })}</p>
      <Consequence
        items={[
          t("issue.consequence.step1"),
          t("issue.consequence.step2"),
          t("issue.consequence.step3", { client: card.client_name }),
          t("issue.consequence.step4"),
        ]}
      />
      {/* D26G-6: реквизитов нет — сказано до клика, кнопка неактивна (ERP всё равно откажет) */}
      {noBank ? <BankDetailsNotice /> : null}
      <ErrorNote message={failure ? t(`issue.reasons.${failure}`) : null} />
      <div className="pf-dec-actions">
        <Button type="primary" htmlType="submit" block loading={issue.isPending} disabled={noBank}>
          {t("issue.submit")}
        </Button>
      </div>
    </form>
  );
}
