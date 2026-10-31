import { useTranslation } from "react-i18next";

import type { PaymentDisplayStatus } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { OWN_STATUS_WORDS } from "./model";

/** Статус счёта словом и цветом: пять статусов — словарь SPEC-v3 §2.4, «не выставлен» и «отменён» — свои слова. */
export function InvoiceStatus({ status }: { status: PaymentDisplayStatus }) {
  const { t } = useTranslation("payments");
  return (
    <StatusTag kind="invoice" status={status}>
      {OWN_STATUS_WORDS.has(status) ? t(`status.${status}`) : undefined}
    </StatusTag>
  );
}
