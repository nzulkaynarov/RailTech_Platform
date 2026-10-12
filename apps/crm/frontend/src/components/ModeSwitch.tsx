import { useQueryClient } from "@tanstack/react-query";
import { Segmented } from "antd";
import { useCallback } from "react";

import { updateMe } from "../api/generated/crm";
import type { UserOut } from "../api/generated/model";
import { keys, useMe } from "../api/queries";
import { useApiErrorToast } from "../hooks/useApiErrorToast";
import { t } from "../i18n/ru";

type Mode = "admin" | "manager";

/**
 * Смена режима сразу перерисовывает меню, чек-лист и маршруты: режим кладётся в кэш `me`
 * до ответа сервера, затем все запросы (включая проверки доступа Refine) перечитываются.
 */
export function useSetUiMode() {
  const client = useQueryClient();
  const onError = useApiErrorToast();
  return useCallback(
    (mode: Mode) => {
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

/** Переключатель Админ/Менеджер (SPEC §10.2): только навигация, права не меняет. */
export function ModeSwitch() {
  const { data: user } = useMe();
  const setMode = useSetUiMode();
  if (!user?.roles.includes("admin")) return null;
  return (
    <Segmented
      size="small"
      className="mode-switch"
      aria-label={t.profile.mode}
      value={user.ui_mode}
      options={[
        { label: t.mode.admin, value: "admin" },
        { label: t.mode.manager, value: "manager" },
      ]}
      onChange={(value) => {
        setMode(value as Mode);
      }}
    />
  );
}
