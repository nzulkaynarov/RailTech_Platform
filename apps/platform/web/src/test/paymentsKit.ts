import { beforeEach } from "vitest";

import { resetPayments } from "../mocks/fixtures/payments";
import { setupApprovalTests } from "./approvalsKit";

export { panelEl, renderAt, signIn } from "./approvalsKit";

/** Подготовка и уборка теста «Счета и оплаты»: то же, что у «На согласовании» (служебки общие), плюс чистые счета и оплаты. */
export function setupPaymentTests(width = 1440): void {
  setupApprovalTests(width);
  beforeEach(() => {
    resetPayments();
  });
}
