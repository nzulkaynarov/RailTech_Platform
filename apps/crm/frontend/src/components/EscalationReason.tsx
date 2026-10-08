import { Space, Tag, Typography } from "antd";

import type { EscalationOut } from "../api/generated/model";
import { t } from "../i18n/ru";

const PRIORITY_COLOR: Record<string, string> = { hot: "red", warm: "orange", info: "blue" };

export function PriorityTag({ priority }: { priority: string }) {
  return (
    <Tag color={PRIORITY_COLOR[priority] ?? "default"}>{t.priority[priority] ?? priority}</Tag>
  );
}

export function EscalationReason({ escalation }: { escalation: EscalationOut }) {
  return (
    <Space direction="vertical" size={4}>
      <Space wrap size={4}>
        <PriorityTag priority={escalation.priority} />
        {escalation.reason_codes.map((code) => (
          <Tag key={code}>{t.reasons[code] ?? code}</Tag>
        ))}
      </Space>
      {escalation.reason_text ? <Typography.Text>{escalation.reason_text}</Typography.Text> : null}
      {escalation.recommendation ? (
        <Typography.Text type="secondary">
          {t.lead.recommendation}: {escalation.recommendation}
        </Typography.Text>
      ) : null}
    </Space>
  );
}
