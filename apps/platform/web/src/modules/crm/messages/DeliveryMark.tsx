import { useTranslation } from "react-i18next";

import type { ThreadMessage } from "../../../shared/api/generated/model";

/**
 * Пометка у ответа менеджера, доставка которого не подтверждена (B-013): `sending` — «Отправляется…»; `unconfirmed`
 * (таймаут Telegram или сбой записи итога, дольше срока CRM) — «Доставка не подтверждена — проверьте у клиента».
 * «Повторить» тем же ключом живёт в поле ответа: в ленте он бесполезен — повтор такого ответа CRM не отправит.
 */
export function DeliveryMark({ message }: { message: ThreadMessage }) {
  const { t } = useTranslation("messages");
  if (message.delivery === "sending") {
    return (
      <p className="pf-msg-delivery pf-msg-delivery--sending">{t("thread.delivery.sending")}</p>
    );
  }
  if (message.delivery === "unconfirmed") {
    return (
      <p className="pf-msg-delivery" role="status">
        {t("thread.delivery.unconfirmedFinal")}
      </p>
    );
  }
  return null;
}
