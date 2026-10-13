import { Column, Pie } from "@ant-design/plots";
import { Col } from "antd";
import { Link } from "react-router";

import type { DealsSummary } from "../../api/generated/model";
import {
  dealPoints,
  isEmpty,
  lostSlices,
  seriesTotals,
  summarize,
} from "../../domain/dashboardCharts";
import { t } from "../../i18n/ru";
import { formatNumber } from "../../lib/format";
import { ChartCard } from "./chartKit";
import { AXES, CHART_HEIGHT, LEGEND_TOP, useChartTheme } from "./chartTheme";

const C = t.charts;

/** «Сделки» (ADR-0019): выиграно/проиграно по дням и отказы по причинам — из `/deals/summary`. */
export function DealsCharts({ summary }: { summary: DealsSummary }) {
  const { theme, token } = useChartTheme();
  const points = dealPoints(summary.daily ?? []);
  const lost = lostSlices(summary.lost_by_reason);
  return (
    <>
      <Col xs={24} md={14} lg={10}>
        <ChartCard
          title={C.deals}
          summary={summarize(C.deals, seriesTotals(points))}
          empty={isEmpty(points)}
          extra={
            <Link to="/deals?stage=open">
              {t.deals.openCount}: {formatNumber(summary.open_count)}
            </Link>
          }
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
            scale={{ color: { range: [token.colorSuccess, token.colorError] } }}
          />
        </ChartCard>
      </Col>
      <Col xs={24} md={10} lg={6}>
        <ChartCard title={C.lostPie} summary={summarize(C.lostPie, lost)} empty={isEmpty(lost)}>
          <Pie
            data={lost}
            angleField="value"
            colorField="label"
            innerRadius={0.6}
            autoFit
            height={CHART_HEIGHT}
            theme={theme}
            legend={{ color: { position: "bottom" } }}
            label={{ text: "value", position: "outside" }}
          />
        </ChartCard>
      </Col>
    </>
  );
}
