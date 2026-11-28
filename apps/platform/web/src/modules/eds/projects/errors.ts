import { useQueryClient } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { grantorNames } from "../../../features/capabilities/useDeniedReason";
import { ApiError } from "../../../shared/api/errors";
import { getGetMyCapabilitiesQueryOptions } from "../../../shared/api/generated/platform-bff";
import { useNotify } from "../../../shared/notify/NotifyProvider";

/** Причина отказа действия по проекту словом: подкод ERP (`details.reason`), иначе по статусу ответа. */
export function reasonText(t: TFunction<"projects">, error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (typeof reason === "string" && t(`errors.${reason}`, { defaultValue: "" }) !== "") {
      return t(`errors.${reason}`);
    }
    if (error.status === 413) return t("errors.payload");
    if (error.status === 403) return t("errors.forbidden");
    if (error.status === 409) return t("errors.contract_transition_not_allowed");
    if (error.status >= 500 || error.status === 0) return t("errors.unavailable");
    return t("errors.unknown");
  }
  return error instanceof TypeError ? t("errors.unavailable") : t("errors.unknown");
}

/** Отказ из-за того, что документ уже в другом статусе (кто-то опередил): карточку надо обновить. */
export function isStale(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

/**
 * Причина отказа с теми же именами, что в подсказке неактивной кнопки (ПОДПИСЬ-1): 403 — «у вас нет такой возможности.
 * Её выдают: <имена>.» (кэш «Мои возможности» или один запрос), остальное — как `reasonText`. `inSentence` — причина
 * встаёт после «Не получилось: » (с маленькой буквы); иначе это законченная фраза сама по себе.
 */
export function useReasonText(): (error: unknown, inSentence: boolean) => Promise<string> {
  const { t } = useTranslation("projects");
  const { t: tc } = useTranslation("capabilities");
  const client = useQueryClient();
  return useCallback(
    async (error, inSentence) => {
      if (!(error instanceof ApiError) || error.status !== 403) return reasonText(t, error);
      const first = inSentence ? t("errors.forbiddenPart") : t("errors.forbidden");
      const names = await client
        .query({ ...getGetMyCapabilitiesQueryOptions(), staleTime: 60_000 })
        .then((mine) => grantorNames(mine.grantors))
        .catch(() => "");
      const head = inSentence ? `${first}.` : first;
      return names === "" ? head : `${head} ${tc("denied.cantGrantors", { names })}`;
    },
    [t, tc, client],
  );
}

/**
 * Одно место для отказов действий на странице проекта (ПОДПИСЬ-1): 403 и 409 говорят словами («Не удалось: …»), а не
 * молчат. Каждое действие, у которого нет своей строки ошибки рядом с формой, отдаёт сюда `onError`.
 */
export function useActionError(failed?: string): (error: unknown) => void {
  const { t } = useTranslation("projects");
  const notify = useNotify();
  const describe = useReasonText();
  return useCallback(
    (error: unknown) => {
      void describe(error, true).then((reason) => {
        notify.error(failed ? `${failed}: ${reason}` : t("errors.failed", { reason }));
      });
    },
    [t, notify, failed, describe],
  );
}

/** Строка «Не получилось: <причина>» для панелей с собственной строкой ошибки; отдаёт готовый текст в `set`. */
export function useFailedText(): (error: unknown, set: (text: string) => void) => void {
  const { t } = useTranslation("projects");
  const describe = useReasonText();
  return useCallback(
    (error, set) => {
      void describe(error, true).then((reason) => {
        set(t("errors.failed", { reason }));
      });
    },
    [t, describe],
  );
}
