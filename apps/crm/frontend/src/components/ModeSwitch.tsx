import { Segmented } from "antd";

import { useMe } from "../api/queries";
import { type UiMode, useSetUiMode } from "../hooks/useSetUiMode";
import { t } from "../i18n/ru";

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
        setMode(value as UiMode);
      }}
    />
  );
}
