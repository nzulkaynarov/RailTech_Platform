import { Alert, App, Button } from "antd";
import { useTranslation } from "react-i18next";

import type { CalcSheet } from "../../../shared/api/generated/model";
import { useNewCalcQuoteVersion } from "../../../shared/api/generated/platform-bff";
import { calcRef, useApplySheet, useErrorText } from "./api";
import { CloseRequestButton } from "./CloseRequest";

/** Причина, выбранная заранее в «Закрыть заявку» после отказа клиента от КП (справочник `request-close-reasons`). */
const CLIENT_CHANGED_MIND = "CHANGED_MIND";

/**
 * Клиент отклонил КП (SPEC-v3 §3.3, D26G-3): причина клиента и решение менеджера — «Новая версия КП» (расчёт снова
 * открывается черновиком версии +1) или «Отказ по заявке» с причиной. Действия — только при `quote.can_revise`.
 */
export function ClientRejection({ sheet }: { sheet: CalcSheet }) {
  const { t } = useTranslation("calc");
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
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
              <CloseRequestButton target={sheet} preselect={CLIENT_CHANGED_MIND} />
            </div>
          </div>
        ) : (
          t("rejection.noRights")
        )
      }
    />
  );
}
