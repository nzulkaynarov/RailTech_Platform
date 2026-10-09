import { Space, Tag, Typography } from "antd";

import type { LeadOut } from "../api/generated/model";
import { t } from "../i18n/ru";

/** Кто ведёт лида: бот, очередь к менеджеру или конкретный человек (имя, а не режим). */
export function Owner({ lead }: { lead: Pick<LeadOut, "owner_mode" | "assigned_user_name"> }) {
  if (lead.owner_mode === "paused") return <Tag color="orange">{t.owner.paused}</Tag>;
  if (lead.owner_mode === "human") {
    return <Typography.Text>{lead.assigned_user_name ?? t.owner.human}</Typography.Text>;
  }
  return (
    <Space size={4} wrap>
      <Typography.Text>{t.owner.bot}</Typography.Text>
      {lead.assigned_user_name ? (
        <Typography.Text type="secondary">
          · {t.owner.responsible} {lead.assigned_user_name}
        </Typography.Text>
      ) : null}
    </Space>
  );
}
