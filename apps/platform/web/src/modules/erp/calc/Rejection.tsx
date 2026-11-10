import { Alert, App, Button, Input, Modal } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CalcSheet } from "../../../shared/api/generated/model";
import {
  useLoseCalcRequest,
  useNewCalcQuoteVersion,
} from "../../../shared/api/generated/platform-bff";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { calcRef, useApplySheet, useErrorText } from "./api";

/** «Отказ по заявке» с обязательной причиной: заявка — стадия «Отказ», резерв снимается (D26G-3). */
function LostModal({ sheet, onClose }: { sheet: CalcSheet; onClose: () => void }) {
  const { t } = useTranslation("calc");
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
  const reasonId = useId();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const lose = useLoseCalcRequest({
    mutation: {
      onSuccess: (next) => {
        apply(next);
        void message.success(t("rejection.lost.done"));
        onClose();
      },
      onError: (e) => {
        setError(errorText(e));
      },
    },
  });
  const text = reason.trim();
  return (
    <Modal
      open
      width={560}
      title={t("rejection.lost.title", { number: sheet.number })}
      onCancel={onClose}
      destroyOnHidden
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("rejection.cancel")}
        </Button>,
        <Button
          key="submit"
          type="primary"
          danger
          loading={lose.isPending}
          disabled={!text}
          onClick={() => {
            setError(null);
            lose.mutate({ number: calcRef(sheet.number), data: { reason: text } });
          }}
        >
          {t("rejection.lost.submit")}
        </Button>,
      ]}
    >
      <div className="pf-calc-stack">
        <FormField id={reasonId} label={t("rejection.lost.reason")} hint={t("rejection.lost.hint")}>
          <Input.TextArea
            id={reasonId}
            value={reason}
            maxLength={1000}
            rows={3}
            aria-required
            aria-describedby={`${reasonId}-hint`}
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
        </FormField>
        <ErrorNote message={error} />
      </div>
    </Modal>
  );
}

/**
 * Клиент отклонил КП (SPEC-v3 §3.3, D26G-3): причина клиента и решение менеджера — «Новая версия КП» (расчёт снова
 * открывается черновиком версии +1) или «Отказ по заявке» с причиной. Действия — только при `quote.can_revise`.
 */
export function ClientRejection({ sheet }: { sheet: CalcSheet }) {
  const { t } = useTranslation("calc");
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
  const [lost, setLost] = useState(false);
  const revise = useNewCalcQuoteVersion({
    mutation: {
      onSuccess: (next) => {
        apply(next);
        void message.success(
          t("rejection.newVersion.done", { version: next.quote?.version ?? "" }),
        );
      },
      onError: (error) => {
        void message.error(errorText(error));
      },
    },
  });
  const quote = sheet.quote;
  if (!quote) return null;
  const closed = sheet.step === "LOST";
  const reason = quote.reject_reason;
  return (
    <Alert
      type={closed ? "info" : "warning"}
      showIcon
      message={
        reason
          ? t("rejection.client", { number: quote.number ?? "", version: quote.version, reason })
          : t("rejection.clientNoReason", { number: quote.number ?? "", version: quote.version })
      }
      description={
        closed ? (
          t("rejection.closed")
        ) : quote.can_revise ? (
          <div className="pf-calc-stack">
            <p>{t("rejection.choose")}</p>
            <div className="pf-calc-row">
              <Button
                type="primary"
                loading={revise.isPending}
                onClick={() => {
                  revise.mutate({ number: calcRef(sheet.number) });
                }}
              >
                {t("rejection.newVersion.button")}
              </Button>
              <Button
                danger
                onClick={() => {
                  setLost(true);
                }}
              >
                {t("rejection.lost.button")}
              </Button>
            </div>
            {lost ? (
              <LostModal
                sheet={sheet}
                onClose={() => {
                  setLost(false);
                }}
              />
            ) : null}
          </div>
        ) : (
          t("rejection.noRights")
        )
      }
    />
  );
}
