import { Button } from "antd";
import { useTranslation } from "react-i18next";

import type { ConversationCard } from "../../../shared/api/generated/model";

/**
 * Вместо поля «От себя», когда отвечать клиенту некуда (CH-1): одна строка причины от CRM (`reply_blocked`) и действие,
 * которое можно сделать сразу — «Позвонить» (только телефон) и «Записать звонок» (заметка команде с заготовкой). Поле
 * «Заметка команде» остаётся всегда.
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
      <p>
        {t(
          `composer.${reason === "phone_only" ? "phoneOnly" : reason === "no_consent" ? "noConsent" : "noContact"}`,
        )}
      </p>
      {reason === "phone_only" ? (
        <div className="pf-msg-reply-state-actions">
          {phone ? (
            <Button href={`tel:${phone.replace(/[^\d+]/g, "")}`}>{t("composer.call")}</Button>
          ) : null}
          <Button onClick={onLogCall}>{t("composer.logCall")}</Button>
        </div>
      ) : null}
    </div>
  );
}
