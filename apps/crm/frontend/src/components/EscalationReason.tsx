import { Space, Tag, Typography } from "antd";

import type { EscalationOut } from "../api/generated/model";
import { reasonLabel } from "../domain/labels";
import { t } from "../i18n/ru";
import { PriorityTag } from "./StageBadge";

export { PriorityTag };

export function EscalationReason({ escalation }: { escalation: EscalationOut }) {
  return (
    <Space direction="vertical" size={4}>
      <Space wrap size={4}>
        <PriorityTag priority={escalation.priority} />
        {escalation.reason_codes.map((code) => (
          <Tag key={code}>{reasonLabel(code)}</Tag>
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
