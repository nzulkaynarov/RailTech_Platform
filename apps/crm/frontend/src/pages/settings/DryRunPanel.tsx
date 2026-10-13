import { Alert, Descriptions, Flex, List, Tag } from "antd";

import type { DryRunResponse } from "../../api/generated/model";
import { LeadLink } from "../../components/EntityLink";
import { t } from "../../i18n/ru";
import { reasonLabel } from "../../domain/labels";

const tags = (codes: string[]) =>
  codes.length ? codes.map((c) => <Tag key={c}>{reasonLabel(c)}</Tag>) : t.common.none;

export function DryRunPanel({ report }: { report: DryRunResponse }) {
  return (
    <Flex vertical gap="small" className="full-width">
      <Descriptions size="small" column={{ xs: 1, md: 3 }} bordered>
        <Descriptions.Item label={t.settings.dialogs}>{report.dialogs}</Descriptions.Item>
        <Descriptions.Item label={t.settings.escalatedNow}>
          {report.escalated_current}
        </Descriptions.Item>
        <Descriptions.Item label={t.settings.escalatedNew}>
          {report.escalated_candidate}
        </Descriptions.Item>
      </Descriptions>
      {report.changed.length ? (
        <List
          size="small"
          header={t.settings.changed}
          dataSource={report.changed}
          renderItem={(row) => (
            <List.Item>
              <LeadLink id={row.lead_id} />
              <span>{tags(row.current)}</span>→<span>{tags(row.candidate)}</span>
            </List.Item>
          )}
        />
      ) : (
        <Alert type="info" showIcon message={`${t.settings.changed}: 0`} />
      )}
    </Flex>
  );
}
