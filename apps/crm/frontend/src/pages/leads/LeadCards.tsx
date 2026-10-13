import { List, Typography } from "antd";
import type { PaginationProps } from "antd";

import type { LeadOut } from "../../api/generated/model";
import { LeadLink } from "../../components/EntityLink";
import { Owner } from "../../components/Owner";
import { PriorityTag, StageBadge } from "../../components/StageBadge";
import { t } from "../../i18n/ru";
import { formatWhen } from "../../lib/time";

type Props = { items: LeadOut[]; loading: boolean; pagination: PaginationProps };

/**
 * Лиды на телефоне — карточками вместо таблицы (дизайн-аудит 2026-10-11, отчёт 2):
 * имя, стадия, ответственный и время последнего сообщения без горизонтальной прокрутки.
 */
export function LeadCards({ items, loading, pagination }: Props) {
  return (
    <List
      className="lead-card-list"
      loading={loading}
      dataSource={items}
      pagination={{ ...pagination, simple: true, align: "center" }}
      renderItem={(lead) => (
        <List.Item key={lead.id}>
          <div className="lead-card-row">
            <Typography.Text strong>
              <LeadLink id={lead.id} name={lead.display_name} />
            </Typography.Text>
            <StageBadge stage={lead.stage} />
            {lead.escalation ? <PriorityTag priority={lead.escalation.priority} /> : null}
          </div>
          <div className="lead-card-row">
            <Owner lead={lead} />
            <Typography.Text type="secondary">
              · {t.leads.score} {lead.score}
            </Typography.Text>
            {lead.last_lead_msg_at ? (
              <Typography.Text type="secondary">
                · {formatWhen(lead.last_lead_msg_at)}
              </Typography.Text>
            ) : null}
          </div>
          {lead.need_summary ? (
            <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }}>
              {lead.need_summary}
            </Typography.Paragraph>
          ) : null}
        </List.Item>
      )}
    />
  );
}
