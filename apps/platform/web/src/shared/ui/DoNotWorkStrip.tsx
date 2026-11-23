import { Alert } from "antd";
import { useTranslation } from "react-i18next";

import type { DoNotWork } from "../api/generated/model";
import { useFormat } from "../lib/useFormat";

/**
 * Полоса «С компанией не работаем: причина» (план Х-8): отметка стоит у компании в ERP, её видят все, кто работает
 * с этой компанией — в карточках контрагента, клиента и проекта. Факты — причина, кто и когда отметил, срок; документы
 * в работе не отменяются, закрыты только новые КП, договор, заказ, заявка и приглашения.
 */
export function DoNotWorkStrip({ mark }: { mark: DoNotWork | null | undefined }) {
  const { t } = useTranslation("ui");
  const fmt = useFormat();
  if (!mark) return null;
  const parts = [
    t("doNotWork.by", {
      name: mark.set_by ?? t("doNotWork.unknown"),
      date: fmt.date(mark.set_at),
    }),
    mark.until ? t("doNotWork.until", { date: fmt.date(mark.until) }) : null,
  ].filter(Boolean);
  return (
    <Alert
      className="pf-dnw"
      type="warning"
      showIcon
      role="status"
      message={`${t("doNotWork.title")}: ${mark.reason}`}
      description={parts.join(" · ")}
    />
  );
}
