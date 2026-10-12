/**
 * «Расходы» с графиками (UX волна 4, `@ant-design/plots`): сегодня против лимитов — `Bullet`,
 * по дням — `Column` стеком работа/тесты, по назначению — кольцевой `Pie`; таблицы с теми же
 * числами — в раскрывающихся блоках под графиками. Модуль грузится лениво из `SpendPage`.
 */
import { Bullet, Column, Pie } from "@ant-design/plots";
import { Card, Col, Collapse, Flex, Row, Statistic, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Link } from "react-router";

import type { LeadSpend, SpendDay, SpendReport, SpendSlice } from "../../api/generated/model";
import {
  isEmpty,
  limitRows,
  purposeSlices,
  seriesTotals,
  spendPoints,
  summarize,
} from "../../domain/dashboardCharts";
import { hasTestSpend, kindLabel, purposeLabel, usd } from "../../domain/spend";
import { t } from "../../i18n/ru";
import { formatDate } from "../../lib/time";
import { ChartCard } from "../dashboard/chartKit";
import { AXES, CHART_HEIGHT, LEGEND_TOP, useChartTheme } from "../dashboard/chartTheme";

const C = t.charts;

function Providers({ report }: { report: SpendReport }) {
  const { theme, token } = useChartTheme();
  const rows = limitRows(report);
  const lines = [
    ...report.providers.map((p) => ({ title: p.provider, spent: p.spent_usd, limit: p.limit_usd })),
    { title: t.spend.softBudget, spent: report.today_usd, limit: report.daily_usd },
  ];
  const text = (spent: number, limit: number) =>
    t.spend.of
      .replace("{spent}", usd(spent))
      .replace("{limit}", limit > 0 ? usd(limit) : t.spend.noLimit);
  return (
    <Card title={t.spend.today} size="small">
      <Typography.Paragraph type="secondary">
        {t.spend.todayHint}{" "}
        <Link className="inline-link" to="/settings?section=budget">
          {t.spend.budgetLink}
        </Link>
      </Typography.Paragraph>
      <Flex gap="small" wrap>
        {lines.map((l) => (
          <Typography.Text key={l.title}>
            <Typography.Text strong>{l.title}</Typography.Text>{" "}
            <Typography.Text type="secondary">{text(l.spent, l.limit)}</Typography.Text>
          </Typography.Text>
        ))}
      </Flex>
      {rows.length ? (
        <div
          role="img"
          className="chart-frame"
          aria-label={summarize(
            C.limits,
            rows.map((r) => ({ label: r.title, value: r.measures[0] ?? 0 })),
            (v) => `${String(v)}%`,
          )}
        >
          <Bullet
            data={rows}
            xField="title"
            rangeField="ranges"
            measureField="measures"
            targetField="targets"
            autoFit
            height={Math.max(120, rows.length * 56)}
            theme={theme}
            color={{
              ranges: [token.colorWarningBg, token.colorFillSecondary],
              measures: [token.colorPrimary],
              targets: [token.colorError],
            }}
            mapField={{
              ranges: C.limitRanges,
              measures: [C.limitSpent],
              targets: [C.limitTarget],
            }}
            legend={LEGEND_TOP}
          />
        </div>
      ) : null}
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

const collapsed = (key: string, label: string, children: React.ReactNode) => (
  <Collapse ghost size="small" items={[{ key, label, children }]} />
);

function Daily({ report, withTests }: { report: SpendReport; withTests: boolean }) {
  const { theme, token } = useChartTheme();
  const points = spendPoints(report.series, withTests);
  return (
    <ChartCard
      title={C.spendDaily}
      summary={summarize(C.spendDaily, seriesTotals(points), usd)}
      empty={isEmpty(points)}
      footer={collapsed(
        "days",
        C.dailyTable,
        <Table
          rowKey="day"
          size="small"
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          dataSource={[...report.series].reverse()}
          columns={dayColumns(withTests)}
        />,
      )}
    >
      <Column
        data={points}
        xField="day"
        yField="value"
        colorField="series"
        stack
        autoFit
        height={CHART_HEIGHT}
        theme={theme}
        axis={AXES}
        legend={LEGEND_TOP}
        scale={{ color: { range: [token.colorPrimary, token.colorWarning] } }}
      />
    </ChartCard>
  );
}

function Purposes({ report }: { report: SpendReport }) {
  const { theme } = useChartTheme();
  const slices = purposeSlices(report.by_purpose);
  return (
    <ChartCard
      title={C.purposePie}
      summary={summarize(C.purposePie, slices, usd)}
      empty={isEmpty(slices)}
      footer={collapsed(
        "purpose",
        C.purposeTable,
        <Table
          rowKey="key"
          size="small"
          pagination={false}
          dataSource={report.by_purpose}
          columns={sliceColumns(purposeLabel, t.spend.purpose)}
        />,
      )}
    >
      <Pie
        data={slices}
        angleField="value"
        colorField="label"
        innerRadius={0.6}
        autoFit
        height={CHART_HEIGHT}
        theme={theme}
        legend={{ color: { position: "right" } }}
        tooltip={{ items: [{ field: "value", valueFormatter: usd }] }}
      />
    </ChartCard>
  );
}

/** Сегодня против лимитов, графики по дням и по назначению, работа/тесты, дорогие лиды. */
export default function SpendCharts({ report }: { report: SpendReport }) {
  const withTests = hasTestSpend(report);
  if (report.total_usd <= 0) return <Providers report={report} />;
  return (
    <>
      <Providers report={report} />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Daily report={report} withTests={withTests} />
        </Col>
        <Col xs={24} lg={10}>
          <Purposes report={report} />
        </Col>
        {withTests ? (
          <Col xs={24} lg={10}>
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
        <Col xs={24} lg={withTests ? 14 : 24}>
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
      </Row>
    </>
  );
}
