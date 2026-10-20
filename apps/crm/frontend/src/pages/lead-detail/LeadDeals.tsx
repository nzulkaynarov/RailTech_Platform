import { List, Space, Tag, Typography } from "antd";
import { Link } from "react-router";

import { useDeals } from "../../api/dealQueries";
import type { LeadDetail } from "../../api/generated/model";
import { EmptyState } from "../../components/EmptyState";
import { PageState } from "../../components/PageState";
import { formatMoney, STAGE_COLORS, stageLabel } from "../../domain/deals";
import { t } from "../../i18n/ru";
import { formatDate } from "../../lib/time";

/**
 * Вкладка «Сделки» карточки лида: сделки этого лида (фильтр `lead_id` в API). Все сделки
 * клиента — по ссылке в карточку клиента.
 */
export function LeadDeals({ lead }: { lead: LeadDetail }) {
  const clientId = lead.client_id ?? null;
  const query = useDeals({ lead_id: lead.id });
  const items = query.data ?? [];
  const all = clientId ? `/clients/${String(clientId)}` : "/deals";
  return (
    <PageState query={query} variant="section">
      {items.length ? (
        <List
          size="small"
          dataSource={items}
          footer={<Link to={all}>{t.lead.dealsAll}</Link>}
          renderItem={(d) => (
            <List.Item key={d.id}>
              <Space direction="vertical" size={0}>
                <Typography.Text>{d.title}</Typography.Text>
                <Space wrap size={4}>
                  <Tag color={STAGE_COLORS[d.stage] ?? "default"}>{stageLabel(d.stage)}</Tag>
                  {d.erp_deal_id ? (
                    <Tag color="cyan">
                      {t.clients.inBackoffice} #{String(d.erp_deal_id)}
                    </Tag>
                  ) : null}
                  <Typography.Text type="secondary">
                    <span style={{ whiteSpace: "nowrap" }}>
                      {formatMoney(d.amount, d.currency)}
                    </span>
                    {d.closed_at ? ` · ${formatDate(d.closed_at)}` : ""}
                  </Typography.Text>
                </Space>
              </Space>
            </List.Item>
          )}
        />
      ) : (
        <Space wrap>
          <EmptyState compact title={t.lead.dealsEmpty} />
          <Link to={all}>{t.lead.dealsAll}</Link>
        </Space>
      )}
    </PageState>
  );
}
