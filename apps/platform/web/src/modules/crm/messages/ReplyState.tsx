import { Button } from "antd";
import { useTranslation } from "react-i18next";

import type { ConversationCard } from "../../../shared/api/generated/model";

const TEXT = {
  phone_only: "phoneOnly",
  no_consent: "noConsent",
  no_email_consent: "noEmailConsent",
  email_undeliverable: "emailUndeliverable",
  no_contact: "noContact",
} as const;

/**
 * Вместо поля «От себя», когда отвечать клиенту некуда (CH-1): одна строка причины от CRM (`reply_blocked`) и действие,
 * которое можно сделать сразу — «Позвонить» (если известен телефон: из карточки, Telegram или контакта клиента) и «Записать
 * звонок» (заметка команде с заготовкой). Поле «Заметка команде» остаётся всегда.
 */
export function ReplyState({
  card,
  onLogCall,
}: {
  card: Pick<ConversationCard, "reply_blocked" | "contacts">;
  onLogCall: () => void;
}) {
  const { t } = useTranslation("messages");
  const reason = card.reply_blocked ?? "no_contact";
  const phone = card.contacts.phone;
  return (
    <div className="pf-msg-reply-state" role="status">
      <p>{t(`composer.${TEXT[reason]}`)}</p>
      {phone ? (
        <div className="pf-msg-reply-state-actions">
          <Button href={`tel:${phone.replace(/[^\d+]/g, "")}`}>{t("composer.call")}</Button>
          <Button onClick={onLogCall}>{t("composer.logCall")}</Button>
        </div>
      ) : null}
    </div>
  );
}
