import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Progress,
  Row,
  Segmented,
  Space,
  Statistic,
  Table,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { useDashboard } from "../../api/adminQueries";
import { refreshDashboard } from "../../api/generated/crm";
import type { DailyStat } from "../../api/generated/model";
import { useMe } from "../../api/queries";
import { StageBadge } from "../../components/StageBadge";
import { t } from "../../i18n/ru";

const STAGE_ORDER = [
  "new",
  "engaged",
  "qualified",
  "handoff",
  "in_progress",
  "won",
  "customer",
  "lost",
  "unresponsive",
];

function Bars({ data }: { data: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(data));
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      {Object.entries(data).map(([key, value]) => (
        <div key={key}>
          <Typography.Text>{t.reasons[key] ?? key}</Typography.Text>
          <Progress percent={Math.round((value / max) * 100)} format={() => value} />
        </div>
      ))}
    </Space>
  );
}

/** Дашборд (SPEC §10.1): воронка, эскалации, время до «Забрать», fallback, стоимость, пробелы. */
export function DashboardPage() {
  const [days, setDays] = useState(30);
  const { data, isLoading } = useDashboard(days);
  const me = useMe();
  const client = useQueryClient();
  const refresh = useMutation({
    mutationFn: refreshDashboard,
    onSuccess: () => client.invalidateQueries({ queryKey: ["dashboard"] }),
  });
  if (isLoading || !data) return <Card loading />;
  const totals = data.totals;
  const stats: [string, string | number][] = [
    [t.dashboard.leads, totals.leads_created],
    [t.dashboard.escalations, totals.escalations],
    [t.dashboard.taken, totals.taken],
    [t.dashboard.won, totals.won],
    [t.dashboard.takeTime, totals.avg_take_minutes ?? "—"],
    [
      t.dashboard.fallback,
      data.fallback_share === null ? "—" : `${String(Math.round(data.fallback_share * 100))}%`,
    ],
    [t.dashboard.cost, totals.cost_usd.toFixed(2)],
    [t.dashboard.gaps, data.open_gaps],
    [t.dashboard.openEscalations, data.open_escalations],
  ];
  const funnel = STAGE_ORDER.filter((s) => data.funnel[s]).map((stage) => ({
    stage,
    n: data.funnel[stage] ?? 0,
  }));

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space wrap>
        <Typography.Text>{t.dashboard.period}</Typography.Text>
        <Segmented
          value={days}
          options={[7, 30, 90]}
          onChange={(v) => {
            setDays(v);
          }}
        />
        {data.refreshed_at ? (
          <Typography.Text type="secondary">
            {t.dashboard.refreshed}: {dayjs(data.refreshed_at).format("DD.MM HH:mm")}
          </Typography.Text>
        ) : null}
        {me.data?.roles.includes("admin") ? (
          <Button
            size="small"
            loading={refresh.isPending}
            onClick={() => {
              refresh.mutate();
            }}
          >
            {t.dashboard.refresh}
          </Button>
        ) : null}
      </Space>
      <Row gutter={[16, 16]}>
        {stats.map(([title, value]) => (
          <Col key={title} xs={12} md={8} xl={6}>
            <Card size="small">
              <Statistic title={title} value={value} />
            </Card>
          </Col>
        ))}
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card size="small" title={t.dashboard.funnel}>
            <Table
              size="small"
              pagination={false}
              showHeader={false}
              rowKey="stage"
              dataSource={funnel}
              columns={[
                { render: (_, r) => <StageBadge stage={r.stage} /> },
                { dataIndex: "n", align: "right" },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title={t.dashboard.reasons}>
            <Bars data={data.escalation_reasons} />
          </Card>
        </Col>
      </Row>
      <Card size="small">
        <Table<DailyStat>
          size="small"
          rowKey="day"
          scroll={{ x: 700 }}
          pagination={{ pageSize: 10 }}
          dataSource={[...data.daily].reverse()}
          columns={[
            { title: "", dataIndex: "day", render: (v: string) => dayjs(v).format("DD.MM") },
            { title: t.dashboard.leads, dataIndex: "leads_created" },
            { title: t.dashboard.escalations, dataIndex: "escalations" },
            { title: t.dashboard.taken, dataIndex: "taken" },
            { title: t.dashboard.won, dataIndex: "won" },
            { title: t.dashboard.lost, dataIndex: "lost" },
            { title: t.dashboard.cost, dataIndex: "cost_usd" },
          ]}
        />
      </Card>
    </Space>
  );
}
