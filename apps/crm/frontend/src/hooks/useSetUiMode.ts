import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { updateMe } from "../api/generated/crm";
import type { UserOut } from "../api/generated/model";
import { keys } from "../api/queries";
import { useApiErrorToast } from "./useApiErrorToast";

export type UiMode = "admin" | "manager";

/**
 * Смена режима сразу перерисовывает меню, чек-лист и маршруты: режим кладётся в кэш `me`
 * до ответа сервера, затем все запросы (включая проверки доступа Refine) перечитываются.
 */
export function useSetUiMode() {
  const client = useQueryClient();
  const onError = useApiErrorToast();
  return useCallback(
    (mode: UiMode) => {
      const previous = client.getQueryData<UserOut>(keys.me);
      if (previous) client.setQueryData<UserOut>(keys.me, { ...previous, ui_mode: mode });
      updateMe({ ui_mode: mode })
        .then(() => client.invalidateQueries())
        .catch((error: unknown) => {
          if (previous) client.setQueryData(keys.me, previous);
          onError(error);
        });
    },
    [client, onError],
  );
}
