import { Tag } from "antd";

import { t } from "../i18n/ru";

const COLORS: Record<string, string> = {
  new: "default",
  engaged: "blue",
  qualified: "geekblue",
  handoff: "orange",
  in_progress: "purple",
  won: "green",
  customer: "cyan",
  lost: "red",
  unresponsive: "default",
};

export function StageBadge({ stage }: { stage: string }) {
  return <Tag color={COLORS[stage] ?? "default"}>{t.stage[stage] ?? stage}</Tag>;
}
