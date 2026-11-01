import { App, Button, Card } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type {
  QuoteApprovalCard,
  QuoteDeliveryLine,
  QuoteDeliveryReason,
  QuoteSendInChannel,
} from "../../../shared/api/generated/model";
import { useSendQuoteByChannel } from "../../../shared/api/generated/platform-bff";
import { type CheckState, Checklist, type ChecklistItem } from "../../../shared/ui/Checklist";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { useRefreshApprovals } from "../decision/errors";

const STATE: Record<QuoteDeliveryLine["status"], CheckState> = {
  sent: "ok",
  published: "ok",
  pending: "pending",
  not_selected: "pending",
  unknown: "pending",
  failed: "fail",
  skipped: "fail",
};

/** «Отправить», если по каналу ещё не отправляли; «Отправить повторно», если не сработало. */
function actionKey(line: QuoteDeliveryLine): "send" | "resend" {
  return line.status === "failed" || line.status === "skipped" ? "resend" : "send";
}

/** Причина отказа «Отправить» из 409 BFF (`details.reason`), иначе — по статусу ответа. */
function sendFailure(error: unknown): QuoteDeliveryReason | "invalid_status" | null {
  if (!(error instanceof ApiError)) return null;
  const reason = error.details["reason"];
  return typeof reason === "string" ? (reason as QuoteDeliveryReason | "invalid_status") : null;
}

/**
 * Отчёт «Отправка клиенту» в карточке КП после одобрения (D17G-2, ERP-11): по строке на канал — Telegram, Кабинет, Почта —
 * со словом статуса и причиной, если не ушло. У того, кто отправляет КП (менеджер заявки, директор), — «Отправить» по
 * невыбранному каналу и «Отправить повторно» по не сработавшему, если канал сейчас доступен. Отправляет ERP; почта — через
 * почтовый сервис CRM, итог письма приходит в отчёт позже.
 */
export function DeliveryReport({ quote }: { quote: QuoteApprovalCard }) {
  const { t } = useTranslation("quotes");
  const { message } = App.useApp();
  const refresh = useRefreshApprovals();
  const [failure, setFailure] = useState<string | null>(null);
  const send = useSendQuoteByChannel({
    mutation: {
      onSuccess: (_card, variables) => {
        setFailure(null);
        void refresh();
        const channel = variables.data.channel;
        void message.success(
          channel === "email"
            ? t("card.delivery.doneEmail")
            : t("card.delivery.done", { channel: t(`form.channels.${channel}.name`) }),
        );
      },
      onError: (error) => {
        void refresh();
        const reason = sendFailure(error);
        setFailure(
          reason === "invalid_status"
            ? t("card.delivery.invalid")
            : t("card.delivery.failed", {
                reason: t(`card.delivery.reason.${reason ?? "send_failed"}`),
              }),
        );
      },
    },
  });
  const delivery = quote.delivery;
  if (!delivery) return null;

  const items: ChecklistItem[] = delivery.lines.map((line) => {
    const channel = t(`form.channels.${line.channel}.name`);
    const status = t(`card.delivery.status.${line.status}`);
    const label = line.reason
      ? t("card.delivery.lineReason", {
          channel,
          status,
          reason: t(`card.delivery.reason.${line.reason}`),
        })
      : t("card.delivery.line", { channel, status });
    const action = actionKey(line);
    return {
      state: STATE[line.status],
      label,
      ...(line.can_send
        ? {
            meta: (
              <Button
                size="small"
                loading={send.isPending && send.variables.data.channel === line.channel}
                disabled={send.isPending}
                aria-label={t("card.delivery.sendLabel", {
                  action: t(`card.delivery.${action}`),
                  channel,
                })}
                onClick={() => {
                  setFailure(null);
                  send.mutate({
                    id: quote.id,
                    data: { channel: line.channel as QuoteSendInChannel },
                  });
                }}
              >
                {t(`card.delivery.${action}`)}
              </Button>
            ),
          }
        : {}),
    };
  });

  return (
    <Card size="small" title={<h2 className="pf-dec-title">{t("card.delivery.title")}</h2>}>
      <p className="pf-hint">{t(`card.delivery.state.${delivery.state}`)}</p>
      {delivery.error ? (
        <p className="pf-dec-warn" role="note">
          {t("card.delivery.error", { reason: t(`card.delivery.reason.${delivery.error}`) })}
        </p>
      ) : null}
      <Checklist items={items} label={t("card.delivery.list")} />
      <ErrorNote message={failure} />
    </Card>
  );
}
