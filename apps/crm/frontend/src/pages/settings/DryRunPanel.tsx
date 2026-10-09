import { Alert, Descriptions, List, Tag } from "antd";
import { Link } from "react-router";

import type { DryRunResponse } from "../../api/generated/model";
import { t } from "../../i18n/ru";
import { reasonLabel } from "../../domain/labels";

const tags = (codes: string[]) =>
  codes.length ? codes.map((c) => <Tag key={c}>{reasonLabel(c)}</Tag>) : t.common.none;

export function DryRunPanel({ report }: { report: DryRunResponse }) {
  return (
    <>
      <Descriptions size="small" column={{ xs: 1, md: 3 }} bordered style={{ margin: "12px 0" }}>
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
              <Link to={`/leads/${String(row.lead_id)}`}>#{row.lead_id}</Link>
              <span>{tags(row.current)}</span>→<span>{tags(row.candidate)}</span>
            </List.Item>
          )}
        />
      ) : (
        <Alert type="info" showIcon message={`${t.settings.changed}: 0`} />
      )}
    </>
  );
}
