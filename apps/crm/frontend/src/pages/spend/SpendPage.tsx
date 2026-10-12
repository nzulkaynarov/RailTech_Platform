import { Card, Col, Flex, Progress, Row, Segmented, Statistic, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";
import { Link } from "react-router";

import type { LeadSpend, SpendDay, SpendReport, SpendSlice } from "../../api/generated/model";
import { useSpend } from "../../api/spendQueries";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import {
  barStatus,
  hasTestSpend,
  kindLabel,
  limitPercent,
  PROVIDER_CONSOLES,
  purposeLabel,
  usd,
} from "../../domain/spend";
import { t } from "../../i18n/ru";
import { formatDate } from "../../lib/time";
import "../admin.css";

const PERIODS = [7, 30, 90];

function Providers({ report }: { report: SpendReport }) {
  const soft = limitPercent(report.today_usd, report.daily_usd);
  return (
    <Card title={t.spend.today} size="small">
      <Typography.Paragraph type="secondary">
        {t.spend.todayHint} <Link to="/settings?section=budget">{t.spend.budgetLink}</Link>
      </Typography.Paragraph>
      <Flex vertical gap="small">
        {report.providers.map((p) => {
          const percent = limitPercent(p.spent_usd, p.limit_usd);
          const limit = p.limit_usd > 0 ? usd(p.limit_usd) : t.spend.noLimit;
          return (
            <div key={p.provider}>
              <Typography.Text strong>{p.provider}</Typography.Text>{" "}
              <Typography.Text type="secondary">
                {t.spend.of.replace("{spent}", usd(p.spent_usd)).replace("{limit}", limit)}
              </Typography.Text>
              {percent !== null && (
                <Progress
                  percent={percent}
                  status={barStatus(percent)}
                  aria-label={`${p.provider}: ${String(percent)}%`}
                />
              )}
            </div>
          );
        })}
        <div>
          <Typography.Text strong>{t.spend.softBudget}</Typography.Text>{" "}
          <Typography.Text type="secondary">
            {t.spend.of
              .replace("{spent}", usd(report.today_usd))
              .replace("{limit}", report.daily_usd > 0 ? usd(report.daily_usd) : t.spend.noLimit)}
          </Typography.Text>
          {soft !== null && (
            <Progress
              percent={soft}
              status={barStatus(soft)}
              aria-label={`${t.spend.softBudget}: ${String(soft)}%`}
            />
          )}
        </div>
      </Flex>
    </Card>
  );
}

const sliceColumns = (label: (key: string) => string, title: string): ColumnsType<SpendSlice> => [
  { title, dataIndex: "key", render: (v: string) => label(v) },
  { title: t.spend.calls, dataIndex: "calls", align: "right", width: 90 },
  { title: t.spend.cost, dataIndex: "cost_usd", align: "right", render: usd, width: 110 },
];

const dayColumns = (withTests: boolean): ColumnsType<SpendDay> => [
  { title: t.spend.day, dataIndex: "day", render: (v: string) => formatDate(v) },
  { title: t.spend.work, dataIndex: "work_usd", align: "right", render: usd },
  ...(withTests
    ? [{ title: t.spend.test, dataIndex: "test_usd", align: "right" as const, render: usd }]
    : []),
];

const leadColumns: ColumnsType<LeadSpend> = [
  {
    title: t.spend.lead,
    dataIndex: "lead_id",
    render: (id: number, r) => (
      <Link to={`/leads/${String(id)}`}>{r.lead_name ?? `${t.spend.lead} #${String(id)}`}</Link>
    ),
  },
  { title: t.spend.calls, dataIndex: "calls", align: "right", width: 90 },
  { title: t.spend.cost, dataIndex: "cost_usd", align: "right", render: usd, width: 110 },
];

function Breakdown({ report }: { report: SpendReport }) {
  const withTests = hasTestSpend(report);
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card title={t.spend.byPurpose} size="small">
          <Table
            rowKey="key"
            size="small"
            pagination={false}
            dataSource={report.by_purpose}
            columns={sliceColumns(purposeLabel, t.spend.purpose)}
          />
        </Card>
      </Col>
      {withTests ? (
        <Col xs={24} lg={12}>
          <Card title={t.spend.byKind} size="small">
            <Table
              rowKey="key"
              size="small"
              pagination={false}
              dataSource={report.by_kind}
              columns={sliceColumns(kindLabel, t.spend.purpose)}
            />
          </Card>
        </Col>
      ) : null}
      <Col xs={24} lg={12}>
        <Card title={t.spend.perLead} size="small">
          <Flex gap="large" wrap>
            <Statistic title={t.spend.leads} value={report.leads} />
            <Statistic title={t.spend.avgLead} value={usd(report.avg_per_lead_usd)} />
          </Flex>
          <Typography.Title level={2} className="section-title">
            {t.spend.topLeads}
          </Typography.Title>
          <Table
            rowKey="lead_id"
            size="small"
            pagination={false}
            dataSource={report.top_leads}
            columns={leadColumns}
          />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card title={t.spend.series} size="small">
          <Table
            rowKey="day"
            size="small"
            pagination={{ pageSize: 10, hideOnSinglePage: true }}
            dataSource={[...report.series].reverse()}
            columns={dayColumns(withTests)}
          />
        </Card>
      </Col>
    </Row>
  );
}

/** «Расходы» (админ): сегодня против лимитов, по дням, по назначению, работа/тесты, лиды. */
export function SpendPage() {
  const [days, setDays] = useState(30);
  const query = useSpend(days);
  const report = query.data;
  return (
    <PageBody>
      <PageHeader
        title={t.page.spend}
        extra={
          <Segmented<number>
            aria-label={t.spend.period}
            value={days}
            onChange={(v) => {
              setDays(v);
            }}
            options={PERIODS.map((n) => ({
              value: n,
              label: t.spend.periodDays.replace("{n}", String(n)),
            }))}
          />
        }
      />
      <PageState query={query}>
        {report && (
          <>
            <Providers report={report} />
            {report.total_usd > 0 ? (
              <Breakdown report={report} />
            ) : (
              <Card size="small">
                <Typography.Text strong>{t.spend.empty}</Typography.Text>
                <Typography.Paragraph type="secondary">{t.spend.emptyHint}</Typography.Paragraph>
              </Card>
            )}
            <Typography.Paragraph type="secondary">
              {t.spend.consoles}{" "}
              {PROVIDER_CONSOLES.map((c, i) => (
                <span key={c.href}>
                  {i > 0 && " · "}
                  <Typography.Link href={c.href} target="_blank" rel="noreferrer">
                    {c.label}
                  </Typography.Link>
                </span>
              ))}
            </Typography.Paragraph>
          </>
        )}
      </PageState>
    </PageBody>
  );
}
