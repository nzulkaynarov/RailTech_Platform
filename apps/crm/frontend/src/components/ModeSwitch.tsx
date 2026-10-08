import { useQueryClient } from "@tanstack/react-query";
import { Segmented } from "antd";

import { updateMe } from "../api/generated/crm";
import { keys, useMe } from "../api/queries";
import { t } from "../i18n/ru";

/** Переключатель Админ/Менеджер (SPEC §10.2): только навигация, права не меняет. */
export function ModeSwitch() {
  const { data: user } = useMe();
  const client = useQueryClient();
  if (!user?.roles.includes("admin")) return null;
  return (
    <Segmented
      size="small"
      value={user.ui_mode}
      options={[
        { label: t.mode.admin, value: "admin" },
        { label: t.mode.manager, value: "manager" },
      ]}
      onChange={(value) => {
        void updateMe({ ui_mode: value as "admin" | "manager" }).then(() =>
          client.invalidateQueries({ queryKey: keys.me }),
        );
      }}
    />
  );
}
