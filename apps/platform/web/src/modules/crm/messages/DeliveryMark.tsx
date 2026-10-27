import { App, Button } from "antd";
import { useTranslation } from "react-i18next";

import type { ThreadMessage } from "../../../shared/api/generated/model";
import { useReplyCrmLead } from "../../../shared/api/generated/platform-bff";
import { useRefreshMessages } from "./actions";
import { sendFailure } from "./labels";

/** Сколько ответ может «отправляться», прежде чем экран назовёт доставку неподтверждённой. */
export const SENDING_GRACE_MS = 60_000;

/**
 * Пометка у ответа менеджера, доставка которого не подтверждена (B-013): «Отправляется…», затем «Доставка не
 * подтверждена» и «Повторить» — тот же текст и тот же ключ повтора, поэтому CRM второе сообщение не отправит (пока
 * первая отправка идёт — «ещё отправляется»). `unconfirmed` — итог так и не узнали, повтор уже ничего не изменит.
 */
export function DeliveryMark({
  lead,
  message,
  canRetry,
  now,
}: {
  lead: string;
  message: ThreadMessage;
  canRetry: boolean;
  now: number;
}) {
  const { t } = useTranslation("messages");
  const { message: toast } = App.useApp();
  const refresh = useRefreshMessages();
  const reply = useReplyCrmLead({
    mutation: {
      onSettled: refresh,
      onError: (error) => {
        void toast.warning(sendFailure(t, error).text);
      },
    },
  });
  if (!message.delivery) return null;
  if (message.delivery === "unconfirmed") {
    return (
      <p className="pf-msg-delivery" role="status">
        {t("thread.delivery.unconfirmedFinal")}
      </p>
    );
  }
  const age = now - Date.parse(message.created_at);
  if (age < SENDING_GRACE_MS) {
    return (
      <p className="pf-msg-delivery pf-msg-delivery--sending">{t("thread.delivery.sending")}</p>
    );
  }
  return (
    <p className="pf-msg-delivery" role="status">
      {t("thread.delivery.unconfirmed")}
      {canRetry && message.retry_key ? (
        <Button
          size="small"
          danger
          loading={reply.isPending}
          onClick={() => {
            reply.mutate({
              lead,
              data: { text: message.text, client_message_id: message.retry_key ?? "" },
            });
          }}
        >
          {t("composer.retry")}
        </Button>
      ) : null}
    </p>
  );
}
