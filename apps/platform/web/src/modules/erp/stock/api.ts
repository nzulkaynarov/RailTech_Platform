import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { SupplierOrderStatus } from "../../../shared/api/generated/model";
import type { QueryStateLabels } from "../../../shared/ui/FormParts";

/** Всё, что меняют склад и закупки: остатки, заказы, расчёт (колонка «Склад»), очередь и счётчики. */
const PREFIXES = [
  "/api/v1/erp/stock",
  "/api/v1/erp/calc",
  "/api/v1/erp/price-requests",
  "/api/v1/queue",
  "/api/v1/menu-counters",
  "/api/v1/notifications",
];

/** После действия: перезапрашивает склад, заказы, расчёт, очередь и счётчики. */
export function useRefreshStock(): () => void {
  const client = useQueryClient();
  return useCallback(() => {
    void client.invalidateQueries({
      predicate: (query) => {
        const head = query.queryKey[0];
        return typeof head === "string" && PREFIXES.some((prefix) => head.startsWith(prefix));
      },
    });
  }, [client]);
}

/** Путь карточки заказа в SPA: бизнес-номер ЗП, а не внутренний id (SPEC-v3 §2.2). */
export function orderPath(number: string): string {
  return `/erp/stock/${encodeURIComponent(number)}`;
}

export const ORDER_STATUSES: readonly SupplierOrderStatus[] = [
  "draft",
  "sent",
  "confirmed",
  "received",
  "cancelled",
];

const KNOWN = new Set([
  "not_enough_stock",
  "below_reserved",
  "below_shipped",
  "transition_not_allowed",
  "order_not_draft",
  "order_closed",
  "order_not_confirmed",
  "order_has_receipts",
  "expected_date_required",
  "supplier_email_required",
  "email_failed",
  "fulfillment_not_ready",
  "product_required",
  "no_shortage",
  "deal_closed",
  "line_not_actual",
  "line_not_goods",
  "reservation_not_active",
  "reservation_not_found",
  "already_answered",
  "request_not_sent",
  "service_not_stocked",
  "calc_not_started",
  "quantity_out_of_range",
  "prices_forbidden",
  "calc_task_not_found",
  "order_not_found",
  "line_not_found",
  "request_and_line_together",
  "nothing_to_change",
  "role_not_permitted",
  "supplier_not_found",
  "product_not_found",
]);

/** Отказ словами: подкод (`details.reason`) из словаря, иначе по статусу, иначе текст BFF. */
export function useErrorText(): (error: unknown) => string {
  const { t } = useTranslation("stock");
  return useCallback(
    (error: unknown) => {
      if (error instanceof ApiError) {
        const reason = error.details["reason"];
        const free = error.details["free"];
        const max = error.details["max"];
        if (typeof reason === "string" && KNOWN.has(reason)) {
          return t(`errors.${reason}`, {
            free: typeof free === "number" ? free : 0,
            max: typeof max === "number" ? max : 0,
          });
        }
        if (error.status === 403) return t("errors.forbidden");
        if (error.status >= 500 || error.status === 0) return t("errors.unavailable");
        return t("errors.other", { message: error.message });
      }
      return t("errors.unavailable");
    },
    [t],
  );
}

/** Тексты состояний запроса склада: не загрузилось, ERP не отвечает, нет права. */
export function useStateLabels(): QueryStateLabels {
  const { t } = useTranslation("stock");
  return {
    retry: t("load.retry"),
    loadError: { title: t("load.loadError.title"), text: t("load.loadError.text") },
    unavailable: { title: t("load.unavailable.title"), text: t("load.unavailable.text") },
    forbidden: { title: t("load.forbidden.title"), text: t("load.forbidden.text") },
  };
}

/** Без пробелов и перевода строки; пустая строка — undefined (поля формы, которых может не быть). */
export function clean(value: string | undefined | null): string | undefined {
  const trimmed = (value ?? "").trim();
  return trimmed === "" ? undefined : trimmed;
}
