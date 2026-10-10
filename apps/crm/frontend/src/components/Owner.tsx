import { Space, Tag, Typography } from "antd";

import type { LeadOut } from "../api/generated/model";
import { ownerModeTag } from "../domain/labels";
import { t } from "../i18n/ru";

/** Кто ведёт лида: бот, бот на паузе (ждёт менеджера) или конкретный человек (имя, а не режим). */
export function Owner({ lead }: { lead: Pick<LeadOut, "owner_mode" | "assigned_user_name"> }) {
  if (lead.owner_mode === "paused") {
    const tag = ownerModeTag("paused");
    return <Tag color={tag.color}>{tag.label}</Tag>;
  }
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
