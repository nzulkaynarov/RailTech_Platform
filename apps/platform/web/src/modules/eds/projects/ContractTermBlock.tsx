import { Button, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ProjectContractActionInAction,
  ProjectContractTerm,
} from "../../../shared/api/generated/model";
import { useFormat } from "../../../shared/lib/useFormat";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { useConfirmAction } from "../../../shared/ui/useConfirmAction";

type Send = (action: ProjectContractActionInAction, extra?: { agreement_number?: string }) => void;

/**
 * Срок подписанного договора (ДС-1): считает ERP при подписании по правилу компании и шаблона, здесь только показ и
 * действия, которые ERP разрешил (`term.actions`): отказ от продления, продление соглашением, новая редакция шаблона.
 */
export function ContractTermBlock({
  term,
  busy,
  pending,
  send,
}: {
  term: ProjectContractTerm;
  busy: boolean;
  pending: string | null;
  send: Send;
}) {
  const { t } = useTranslation("projects");
  const { date } = useFormat();
  const confirmAction = useConfirmAction();
  const fieldId = useId();
  const [agreement, setAgreement] = useState("");
  const may = (action: ProjectContractTerm["actions"][number]) => term.actions.includes(action);

  return (
    <section className="pf-ctpl" aria-label={t("contract.term.title")} data-testid="contract-term">
      <p className="pf-ctpl-head">
        <TermTag state={term.state} />
        <span>
          {term.valid_until
            ? t("contract.term.line", {
                from: date(term.valid_from),
                until: date(term.valid_until),
              })
            : t("contract.term.lineOpen", { from: date(term.valid_from) })}
        </span>
      </p>
      {term.state === "renews" && term.last_notice_date ? (
        <p className="pf-hint">
          {t("contract.term.renewsHint", { notice: date(term.last_notice_date) })}
        </p>
      ) : null}
      {term.declined_by ? (
        <p className="pf-hint">{t(`contract.term.declined.${term.declined_by}`)}</p>
      ) : null}
      {term.foreign && term.renewal === "by_agreement" ? (
        <p className="pf-hint">{t("contract.term.foreign")}</p>
      ) : null}
      {term.renewals_count > 0 ? (
        <p className="pf-hint">{t("contract.term.renewals", { count: term.renewals_count })}</p>
      ) : null}
      {term.template_edition ? (
        <p className="pf-hint">
          {term.newer_edition
            ? t("contract.term.editionNewer", {
                edition: term.template_edition,
                newer: term.newer_edition,
              })
            : t("contract.term.edition", { edition: term.template_edition })}
        </p>
      ) : null}
      {term.confidentiality_years || term.trade_secret_indefinite ? (
        <p className="pf-hint">
          {t("contract.term.nda", { years: term.confidentiality_years ?? 0 })}
          {term.trade_secret_indefinite ? ` ${t("contract.term.ndaIndefinite")}` : ""}
        </p>
      ) : null}

      {may("renew") ? (
        <form
          className="pf-ctpl-row"
          aria-label={t("contract.term.action.renew")}
          onSubmit={(event) => {
            event.preventDefault();
            if (busy) return;
            send("renew", agreement.trim() ? { agreement_number: agreement.trim() } : {});
          }}
        >
          <label htmlFor={fieldId} className="pf-hint">
            {t("contract.term.agreement")}
          </label>
          <Input
            id={fieldId}
            value={agreement}
            maxLength={64}
            style={{ maxWidth: 220 }}
            onChange={(event) => {
              setAgreement(event.target.value);
            }}
          />
          <Button type="primary" htmlType="submit" loading={pending === "renew"} disabled={busy}>
            {t("contract.term.action.renew")}
          </Button>
        </form>
      ) : null}
      {may("send_new_edition") ? (
        <Button
          loading={pending === "send_new_edition"}
          disabled={busy}
          onClick={() => {
            send("send_new_edition");
          }}
        >
          {t("contract.term.action.send_new_edition")}
        </Button>
      ) : null}
      {may("decline_renewal") ? (
        <Button
          danger
          loading={pending === "decline_renewal"}
          disabled={busy}
          onClick={() => {
            confirmAction({
              action: t("contract.term.action.decline_renewal"),
              object: "",
              danger: true,
              summary: t("contract.term.declineConfirm", {
                until: term.valid_until ? date(term.valid_until) : "",
              }),
              onConfirm: () => {
                send("decline_renewal");
              },
            });
          }}
        >
          {t("contract.term.action.decline_renewal")}
        </Button>
      ) : null}
    </section>
  );
}

function TermTag({ state }: { state: ProjectContractTerm["state"] }) {
  const { t } = useTranslation("projects");
  const label = t(`contract.term.state.${state}`);
  if (state === "renews") return <StatusTag tone="green">{label}</StatusTag>;
  if (state === "ends") return <StatusTag tone="gold">{label}</StatusTag>;
  if (state === "expired") return <StatusTag tone="red">{label}</StatusTag>;
  return <StatusTag tone="default">{label}</StatusTag>;
}
