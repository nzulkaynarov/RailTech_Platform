import { Space, Tag, Typography } from "antd";

import type { LeadOut } from "../api/generated/model";
import { ownerModeTag } from "../domain/labels";
import { t } from "../i18n/ru";

/**
 * Кто отвечает за лида. Ответственный — всегда человек (как assignee в Intercom/Front);
 * «ведёт бот» и «бот на паузе» — режим переписки, показывается тегом рядом с именем.
 */
export function Owner({ lead }: { lead: Pick<LeadOut, "owner_mode" | "assigned_user_name"> }) {
  const name = lead.assigned_user_name;
  if (lead.owner_mode === "human") {
    return <Typography.Text>{name ?? t.owner.human}</Typography.Text>;
  }
  const mode = lead.owner_mode === "paused" ? ownerModeTag("paused") : ownerModeTag("bot");
  return (
    <Space size={4} wrap>
      {name ? <Typography.Text>{name}</Typography.Text> : null}
      <Tag color={mode.color}>{lead.owner_mode === "paused" ? mode.label : t.owner.botLeads}</Tag>
    </Space>
  );
}
