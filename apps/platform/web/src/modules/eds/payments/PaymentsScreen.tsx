import { PaymentList } from "./PaymentList";
import { MemoView } from "./MemoView";
import { PaymentByNumber, PaymentView } from "./PaymentView";
import { isNumericId, isUuid } from "./model";

import "../decision/decision.css";
import "./payments.css";

/**
 * EDS · Счета и оплаты бухгалтера: список `/eds/payments` (счета по вкладкам и служебки к оплате), карточка счёта
 * `/eds/payments/142`, карточка служебки `/eds/payments/<uuid документа>`, а также адрес по номеру `СЧ-2026/142`.
 */
export function PaymentsScreen({ objectId }: { objectId?: string | undefined }) {
  if (!objectId) return <PaymentList />;
  if (isNumericId(objectId)) return <PaymentView id={Number(objectId)} />;
  if (isUuid(objectId)) return <MemoView id={objectId.toLowerCase()} />;
  return <PaymentByNumber number={objectId} />;
}
