/**
 * Графики дашборда (SPEC §10.1, UX волна 4) на `@ant-design/plots`. Модуль грузится лениво
 * (`React.lazy` в `DashboardPage`), чтобы библиотека графиков не попадала в другие страницы.
 */
import { Bar, Column, Funnel, Gauge, Line } from "@ant-design/plots";
import { Col, Row } from "antd";

import type { Dashboard, DealsSummary } from "../../api/generated/model";
import {
  botPoints,
  flowPoints,
  funnelSlices,
  isEmpty,
  reasonSlices,
  seriesTotals,
  summarize,
} from "../../domain/dashboardCharts";
import { t } from "../../i18n/ru";
import { ChartCard } from "./chartKit";
import { AXES, CHART_HEIGHT, LEGEND_TOP, useChartTheme } from "./chartTheme";
import { DealsCharts } from "./DealsCharts";

const C = t.charts;

function FlowChart({ daily }: { daily: Dashboard["daily"] }) {
  const { theme } = useChartTheme();
  const data = flowPoints(daily);
  return (
    <ChartCard title={C.flow} summary={summarize(C.flow, seriesTotals(data))} empty={isEmpty(data)}>
      <Line
        data={data}
        xField="day"
        yField="value"
        colorField="series"
        autoFit
        height={CHART_HEIGHT}
        theme={theme}
        axis={AXES}
        legend={LEGEND_TOP}
      />
    </ChartCard>
  );
}

function FunnelChart({ funnel }: { funnel: Record<string, number> }) {
  const { theme } = useChartTheme();
  const data = funnelSlices(funnel);
  const total = data.reduce((sum, s) => sum + s.value, 0);
  const title = `${C.funnel} · ${t.dashboard.funnelTotal}: ${String(total)}`;
  return (
    <ChartCard title={title} summary={summarize(title, data)} empty={isEmpty(data)}>
      <Funnel
        data={data}
        xField="label"
        yField="value"
        autoFit
        height={CHART_HEIGHT}
        theme={theme}
        legend={false}
        label={{ text: (d: { label: string; value: number }) => `${d.label}: ${String(d.value)}` }}
      />
    </ChartCard>
  );
}

function ReasonsChart({ reasons }: { reasons: Record<string, number> }) {
  const { theme, token } = useChartTheme();
  const data = reasonSlices(reasons);
  return (
    <ChartCard title={C.reasons} summary={summarize(C.reasons, data)} empty={isEmpty(data)}>
      <Bar
        data={data}
        xField="label"
        yField="value"
        autoFit
        height={CHART_HEIGHT}
        theme={theme}
        axis={AXES}
        style={{ fill: token.colorPrimary }}
        label={{ text: "value", position: "right" }}
      />
    </ChartCard>
  );
}

function BotCharts({ daily, share }: { daily: Dashboard["daily"]; share: number | null }) {
  const { theme, token } = useChartTheme();
  const points = botPoints(daily);
  const pct = share === null ? null : Math.round(share * 100);
  return (
    <>
      <Col xs={24} md={8}>
        <ChartCard
          title={C.fallbackGauge}
          summary={`${C.fallbackGauge}: ${pct === null ? t.common.none : `${String(pct)}%`}`}
          empty={pct === null}
        >
          <Gauge
            data={{ target: pct ?? 0, total: 100, name: C.fallbackGauge }}
            autoFit
            height={CHART_HEIGHT}
            theme={theme}
            scale={{ color: { range: [token.colorWarning, token.colorFillSecondary] } }}
            style={{ textContent: (target: number) => `${String(target)}%` }}
            legend={false}
          />
        </ChartCard>
      </Col>
      <Col xs={24} md={16}>
        <ChartCard
          title={C.botDaily}
          summary={summarize(C.botDaily, seriesTotals(points))}
          empty={isEmpty(points)}
        >
          <Column
            data={points}
            xField="day"
            yField="value"
            colorField="series"
            group
            autoFit
            height={CHART_HEIGHT}
            theme={theme}
            axis={AXES}
            legend={LEGEND_TOP}
          />
        </ChartCard>
      </Col>
    </>
  );
}

/** Поток и воронка, причины и сделки, работа бота — сверху вниз, по 1–2 графика в ряд. */
export default function DashboardCharts({
  data,
  deals,
}: {
  data: Dashboard;
  deals: DealsSummary | undefined;
}) {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={16}>
        <FlowChart daily={data.daily} />
      </Col>
      <Col xs={24} lg={8}>
        <FunnelChart funnel={data.funnel} />
      </Col>
      <Col xs={24} lg={deals ? 8 : 24}>
        <ReasonsChart reasons={data.escalation_reasons} />
      </Col>
      {deals ? <DealsCharts summary={deals} /> : null}
      <BotCharts daily={data.daily} share={data.fallback_share} />
    </Row>
  );
}
