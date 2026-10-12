import { ArrowRightOutlined } from "@ant-design/icons";
import { Card, Statistic, Table, Typography } from "antd";
import { Link } from "react-router";

import { useDealsSummary } from "../../api/dealQueries";
import type { ReasonCount } from "../../api/generated/model";
import { PageState } from "../../components/PageState";
import { formatMoney } from "../../domain/deals";
import { t } from "../../i18n/ru";

const REASON_COLUMNS = [
  { title: t.deals.reason, dataIndex: "reason" },
  { title: t.deals.count, dataIndex: "count", align: "right" as const, width: 90 },
];

/** Сделки за период (Q-013): выигрыш числом и суммой, отказы по причинам. Клик — к списку. */
export function DealsPanel({ days }: { days: number }) {
  const query = useDealsSummary(days);
  const data = query.data;
  const sums = data?.won_amounts.map((s) => formatMoney(s.amount, s.currency)).join(" · ");
  return (
    <Card size="small" title={t.deals.summaryTitle}>
      <PageState query={query} variant="section" ready={Boolean(data)}>
        {data ? (
          <>
            <div className="metric-grid">
              <Link to="/deals?stage=won" className="metric-card--link">
                <Card size="small" className="metric-card" hoverable>
                  <Statistic
                    title={t.deals.wonCount}
                    value={data.won_count}
                    suffix={<ArrowRightOutlined aria-hidden className="metric-arrow" />}
                  />
                </Card>
              </Link>
              <Card size="small" className="metric-card">
                <Statistic title={t.deals.wonSum} value={sums || t.common.none} />
              </Card>
              <Link to="/deals?stage=lost" className="metric-card--link">
                <Card size="small" className="metric-card" hoverable>
                  <Statistic
                    title={t.deals.lostCount}
                    value={data.lost_count}
                    suffix={<ArrowRightOutlined aria-hidden className="metric-arrow" />}
                  />
                </Card>
              </Link>
              <Link to="/deals?stage=open" className="metric-card--link">
                <Card size="small" className="metric-card" hoverable>
                  <Statistic title={t.deals.openCount} value={data.open_count} />
                </Card>
              </Link>
            </div>
            <Typography.Title level={3} className="section-title">
              {t.deals.lostByReason}
            </Typography.Title>
            <Table<ReasonCount>
              rowKey="reason"
              size="small"
              pagination={false}
              dataSource={data.lost_by_reason}
              columns={REASON_COLUMNS}
              locale={{ emptyText: <Typography.Text>{t.deals.lostEmpty}</Typography.Text> }}
            />
          </>
        ) : null}
      </PageState>
    </Card>
  );
}
