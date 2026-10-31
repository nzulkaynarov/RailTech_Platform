import { useTranslation } from "react-i18next";

import type { TicketStatus } from "../../shared/api/generated/model";
import { StatusTag } from "../../shared/ui/StatusTag";

/** Статус обращения словом и цветом (SPEC-v3 §5.2): Новое, В работе, Решено. */
export function TicketStatusTag({ status }: { status: TicketStatus }) {
  const { t } = useTranslation("help");
  return (
    <StatusTag kind="ticket" status={status}>
      {t(`ticket.status.${status}`)}
    </StatusTag>
  );
}
