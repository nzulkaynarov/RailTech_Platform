import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { CalcSheet } from "../../../shared/api/generated/model";
import { getGetCalcSheetQueryKey } from "../../../shared/api/generated/platform-bff";
import type { QueryStateLabels } from "../../../shared/ui/FormParts";

/** Все запросы расчёта начинаются с этих префиксов ключа (orval): по ним сбрасывается кэш после действия. */
const CALC_KEYS = ["/api/v1/erp/calc"];

/** Номер заявки в адресе API (в номере могут быть символы, которые нужно закодировать). */
export function calcRef(number: string): string {
  return encodeURIComponent(number);
}

/** Путь расчёта в SPA: бизнес-номер ЗВ, а не внутренний id (SPEC-v3 §2.2). */
export function calcPath(number: string): string {
  return `/erp/calc/${encodeURIComponent(number)}`;
}

/** Ответ действия — новый расчёт: кладётся в кэш карточки, список и счётчики перезапрашиваются. */
export function useApplySheet(): (sheet: CalcSheet) => void {
  const client = useQueryClient();
  return useCallback(
    (sheet: CalcSheet) => {
      client.setQueryData(getGetCalcSheetQueryKey(calcRef(sheet.number)), sheet);
      void client.invalidateQueries({
        predicate: (query) => {
          const head = query.queryKey[0];
          return (
            typeof head === "string" &&
            CALC_KEYS.some((key) => head.startsWith(key)) &&
            head !== getGetCalcSheetQueryKey(calcRef(sheet.number))[0]
          );
        },
      });
    },
    [client],
  );
}

const KNOWN = new Set([
  "visas_missing",
  "quote_not_draft",
  "line_incomplete",
  "purchase_required",
  "client_price_below_cost",
  "markup_out_of_range",
  "zone_not_permitted",
  "cost_forbidden",
]);

/** Отказ словами: подкод (`details.reason`) из словаря, иначе по статусу, иначе текст BFF. */
export function useErrorText(): (error: unknown) => string {
  const { t } = useTranslation("calc");
  return useCallback(
    (error: unknown) => {
      if (error instanceof ApiError) {
        const reason = error.details["reason"];
        if (typeof reason === "string" && KNOWN.has(reason)) return t(`errors.${reason}`);
        if (error.status === 403) return t("errors.forbidden");
        if (error.status >= 500 || error.status === 0) return t("errors.unavailable");
        return t("errors.other", { message: error.message });
      }
      return t("errors.unavailable");
    },
    [t],
  );
}

/** Тексты состояний запроса расчёта: не загрузилось, ERP не отвечает, нет права. */
export function useStateLabels(): QueryStateLabels {
  const { t } = useTranslation("calc");
  return {
    retry: t("load.retry"),
    loadError: { title: t("load.loadError.title"), text: t("load.loadError.text") },
    unavailable: { title: t("load.unavailable.title"), text: t("load.unavailable.text") },
    forbidden: { title: t("load.forbidden.title"), text: t("load.forbidden.text") },
  };
}

/** Срок расчёта прошёл: календарная дата компании позже срока. */
export function isOverdue(due: string, today: string): boolean {
  return due < today;
}

/** Почему «Расчёт готов» неактивна: «не черновик» уточняется состоянием КП (у директора, одобрено, отклонено). */
export function readyHintKey(sheet: Pick<CalcSheet, "ready" | "quote">): string {
  const blocker = sheet.ready.blocker;
  const state = sheet.quote?.state;
  if (
    blocker === "not_draft" &&
    (state === "at_director" || state === "approved" || state === "rejected")
  ) {
    return state;
  }
  return blocker ?? "not_draft";
}
