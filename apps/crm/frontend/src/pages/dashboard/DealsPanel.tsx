import { ArrowRightOutlined } from "@ant-design/icons";
import { Card, Statistic, Table, Typography } from "antd";
import { Link } from "react-router";

import { useDealsSummary } from "../../api/dealQueries";
import type { DealsSummary, ReasonCount } from "../../api/generated/model";
import { PageState } from "../../components/PageState";
import { formatMoney } from "../../domain/deals";
import { formatNumber } from "../../lib/format";
import { t } from "../../i18n/ru";

const REASON_COLUMNS = [
  { title: t.deals.reason, dataIndex: "reason" },
  { title: t.deals.count, dataIndex: "count", align: "right" as const, width: 90 },
];

/**
 * Сумма выигрыша: без сумм — «—» и подсказка, сколько сделок без суммы; частичная сумма
 * помечается как неполная (аудит 2026-10-12: «$0» при неуказанных суммах вводил в заблуждение).
 */
export function wonSum(data: DealsSummary): { value: string; hint: string | null } {
  const missing = data.won_without_amount ?? 0;
  const known = data.won_count - missing;
  const n = String(missing);
  if (!data.won_count) return { value: t.common.none, hint: null };
  if (!known) return { value: t.common.none, hint: t.deals.wonSumNone.replace("{n}", n) };
  const value = data.won_amounts
    .filter((s) => Number(s.amount) > 0)
    .map((s) => formatMoney(s.amount, s.currency))
    .join(" · ");
  return {
    value: value || t.common.none,
    hint: missing ? t.deals.wonSumMissing.replace("{n}", n) : null,
  };
}

/** Сделки за период (Q-013): выигрыш числом и суммой, отказы по причинам. Клик — к списку. */
export function DealsPanel({ days }: { days: number }) {
  const query = useDealsSummary(days);
  const data = query.data;
  const sum = data ? wonSum(data) : null;
  return (
    <Card size="small" title={<h2 className="card-heading">{t.deals.summaryTitle}</h2>}>
      <PageState query={query} variant="section" ready={Boolean(data)}>
        {data ? (
          <>
            <div className="metric-grid">
              <Link to="/deals?stage=won" className="metric-card--link">
                <Card size="small" className="metric-card" hoverable>
                  <Statistic
                    title={t.deals.wonCount}
                    value={formatNumber(data.won_count)}
                    suffix={<ArrowRightOutlined aria-hidden className="metric-arrow" />}
                  />
                </Card>
              </Link>
              <Card size="small" className="metric-card">
                <Statistic title={t.deals.wonSum} value={sum?.value ?? t.common.none} />
                {sum?.hint ? (
                  <Typography.Text type="secondary" className="metric-hint">
                    {sum.hint}
                  </Typography.Text>
                ) : null}
              </Card>
              <Link to="/deals?stage=lost" className="metric-card--link">
                <Card size="small" className="metric-card" hoverable>
                  <Statistic
                    title={t.deals.lostCount}
                    value={formatNumber(data.lost_count)}
                    suffix={<ArrowRightOutlined aria-hidden className="metric-arrow" />}
                  />
                </Card>
              </Link>
              <Link to="/deals?stage=open" className="metric-card--link">
                <Card size="small" className="metric-card" hoverable>
                  <Statistic title={t.deals.openCount} value={formatNumber(data.open_count)} />
                </Card>
              </Link>
            </div>
            <Typography.Title level={3} className="section-title">
              {t.deals.lostByReason}
            </Typography.Title>
            {data.lost_by_reason.length ? (
              <Table<ReasonCount>
                rowKey="reason"
                size="small"
                pagination={false}
                dataSource={data.lost_by_reason}
                columns={REASON_COLUMNS}
              />
            ) : (
              <Typography.Text type="secondary">{t.deals.lostEmpty}</Typography.Text>
            )}
          </>
        ) : null}
      </PageState>
    </Card>
  );
}
