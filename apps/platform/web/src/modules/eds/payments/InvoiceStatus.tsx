import { useTranslation } from "react-i18next";

import type { PaymentDisplayStatus } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { OWN_STATUS_TONE } from "./model";

/** Статус счёта словом и цветом: пять статусов — словарь SPEC-v3 §2.4, «не выставлен» и «отменён» — свои слова. */
export function InvoiceStatus({ status }: { status: PaymentDisplayStatus }) {
  const { t } = useTranslation("payments");
  const own = OWN_STATUS_TONE[status];
  if (own) return <StatusTag tone={own}>{t(`status.${status}`)}</StatusTag>;
  return <StatusTag kind="invoice" status={status} />;
}
