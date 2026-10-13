import { Tag, Typography } from "antd";

import type { LeadOut } from "../api/generated/model";
import { whoLeads } from "../domain/owner";

/**
 * «Кто ведёт»: Бот / Ждёт менеджера · N мин / Имя менеджера — одно значение в ячейке
 * (как assignee в Intercom/Front). Во время передачи — никогда не «Бот».
 */
export function Owner({
  lead,
}: {
  lead: Pick<LeadOut, "owner_mode" | "assigned_user_name" | "escalation">;
}) {
  const who = whoLeads(lead);
  if (who.kind === "human") return <Typography.Text>{who.label}</Typography.Text>;
  const color = who.kind === "waiting" ? "warning" : who.kind === "paused" ? "default" : "blue";
  return <Tag color={color}>{who.label}</Tag>;
}
