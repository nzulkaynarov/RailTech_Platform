import { Skeleton } from "antd";
import { useTranslation } from "react-i18next";

import { useGetCrmLead } from "../../../shared/api/generated/platform-bff";
import { EmptyState } from "../../../shared/ui/EmptyState";
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
  const { t } = useTranslation("leads");
  const card = useGetCrmLead(lead ?? "", { query: { enabled: lead !== null } });
  if (lead === null) return <RequestForm lead={null} clientId={clientId} onCancel={onCancel} />;
  if (card.isPending) return <Skeleton active paragraph={{ rows: 6 }} title={false} />;
  if (card.isError) {
    return <EmptyState level={3} compact title={t("loadError.title")} text={t("loadError.text")} />;
  }
  return (
    <RequestForm lead={card.data} clientId={clientId} letterFrom={letterFrom} onCancel={onCancel} />
  );
}
