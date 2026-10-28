import { Skeleton } from "antd";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import { useGetCrmLead } from "../../../shared/api/generated/platform-bff";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { canCreateFromLead } from "../common/access";
import { type LetterSource, RequestForm } from "./RequestForm";

/**
 * Форма «Создать заявку» из лида (`lead`) или из карточки клиента (`clientId`): для лида сначала читается его карточка —
 * контакты, согласие и запрос, собранный ботом, заполняют форму.
 */
export function CreateRequest({
  lead,
  clientId,
  letterFrom = null,
  onCancel,
}: {
  lead: string | null;
  clientId: number | null;
  /** Вложение сообщения лида — письмо директору («В заявку» в «Ждут ответа») */
  letterFrom?: LetterSource | null;
  onCancel: () => void;
}) {
  const { t } = useTranslation(["leads", "request"]);
  const { me } = useAuth();
  const card = useGetCrmLead(lead ?? "", { query: { enabled: lead !== null } });
  if (lead === null) return <RequestForm lead={null} clientId={clientId} onCancel={onCancel} />;
  if (card.isPending) return <Skeleton active paragraph={{ rows: 6 }} title={false} />;
  if (card.isError) {
    return (
      <EmptyState
        level={3}
        compact
        title={t("leads:loadError.title")}
        text={t("leads:loadError.text")}
      />
    );
  }
  // Чужой лид (адрес `create=1` вручную или устаревшая ссылка): формы нет — и вложение из переписки в EDS не копируется.
  if (!canCreateFromLead(me, card.data.assigned)) {
    return (
      <EmptyState
        level={3}
        compact
        title={t("request:title")}
        text={t("request:errors.not_lead_owner")}
      />
    );
  }
  return (
    <RequestForm lead={card.data} clientId={clientId} letterFrom={letterFrom} onCancel={onCancel} />
  );
}
