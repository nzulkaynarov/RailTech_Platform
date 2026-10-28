import { useTranslation } from "react-i18next";

import type { TicketStatus } from "../../shared/api/generated/model";
import type { StatusTone } from "../../shared/lib/statuses";
import { StatusTag } from "../../shared/ui/StatusTag";

const STATUS_TONE: Record<TicketStatus, StatusTone> = {
  new: "blue",
  in_progress: "gold",
  resolved: "green",
};

/** Статус обращения словом и цветом (SPEC-v3 §5.2): Новое, В работе, Решено. */
export function TicketStatusTag({ status }: { status: TicketStatus }) {
  const { t } = useTranslation("help");
  return <StatusTag tone={STATUS_TONE[status]}>{t(`ticket.status.${status}`)}</StatusTag>;
}
