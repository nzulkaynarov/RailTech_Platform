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
import { useState } from "react";
import { Link } from "react-router";

import { useDashboard } from "../../api/adminQueries";
import { refreshDashboard } from "../../api/generated/crm";
import type { DailyStat, Dashboard } from "../../api/generated/model";
import { usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { StageBadge } from "../../components/StageBadge";
import { reasonLabel, STAGE_ORDER } from "../../domain/labels";
import { leadFiltersToSearch } from "../../hooks/leadFilters";
import { t } from "../../i18n/ru";
import { formatDate, formatDateTime, tashkent } from "../../lib/time";

/** Ссылка на список лидов с фильтром (drill-down с дашборда, аудит UI U-06). */
const leadsLink = (filters: { stage?: string; from?: string; to?: string }) =>
  `/leads?${leadFiltersToSearch({ ...filters, page: 1 }).toString()}`;

function Bars({ data }: { data: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(data));
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      {Object.entries(data).map(([key, value]) => (
        <div key={key}>
          <Typography.Text>{reasonLabel(key)}</Typography.Text>
          <Progress percent={Math.round((value / max) * 100)} format={() => value} />
        </div>
      ))}
    </Space>
  );
}

type Tile = [string, string | number, string | null];

function tiles(data: Dashboard, days: number): Tile[] {
  const totals = data.totals;
  const now = tashkent(new Date());
  const period = {
    from: now.subtract(days - 1, "day").format("YYYY-MM-DD"),
    to: now.format("YYYY-MM-DD"),
  };
  const share = data.fallback_share;
  return [
    [t.dashboard.leads, totals.leads_created, leadsLink(period)],
    [t.dashboard.escalations, totals.escalations, null],
    [t.dashboard.taken, totals.taken, null],
    [t.dashboard.won, totals.won, leadsLink({ stage: "won" })],
    [t.dashboard.takeTime, totals.avg_take_minutes ?? t.common.none, null],
    [
      t.dashboard.fallback,
      share === null ? t.common.none : `${String(Math.round(share * 100))}%`,
      null,
    ],
    [t.dashboard.cost, totals.cost_usd.toFixed(2), null],
    [t.dashboard.gaps, data.open_gaps, "/gaps"],
    [t.dashboard.openEscalations, data.open_escalations, "/inbox"],
  ];
}

function Tiles({ data, days }: { data: Dashboard; days: number }) {
  return (
    <Row gutter={[16, 16]}>
      {tiles(data, days).map(([title, value, link]) => (
        <Col key={title} xs={12} md={8} xl={6}>
          <Card size="small" hoverable={Boolean(link)}>
            {link ? (
              <Link to={link}>
                <Statistic title={title} value={value} />
              </Link>
            ) : (
              <Statistic title={title} value={value} />
            )}
          </Card>
        </Col>
      ))}
    </Row>
  );
}

function Funnel({ funnel }: { funnel: Record<string, number> }) {
  const rows = STAGE_ORDER.filter((s) => funnel[s]).map((stage) => ({ stage, n: funnel[stage] }));
  return (
    <Table
      size="small"
      pagination={false}
      showHeader={false}
      rowKey="stage"
      dataSource={rows}
      columns={[
        {
          render: (_, r) => (
            <Link to={leadsLink({ stage: r.stage })}>
              <StageBadge stage={r.stage} />
            </Link>
          ),
        },
        { dataIndex: "n", align: "right" },
      ]}
    />
  );
}

const DAILY_COLUMNS = [
  { title: t.dashboard.day, dataIndex: "day", render: (v: string) => formatDate(v) },
  { title: t.dashboard.leads, dataIndex: "leads_created" },
  { title: t.dashboard.escalations, dataIndex: "escalations" },
  { title: t.dashboard.taken, dataIndex: "taken" },
  { title: t.dashboard.won, dataIndex: "won" },
  { title: t.dashboard.lost, dataIndex: "lost" },
  { title: t.dashboard.cost, dataIndex: "cost_usd", render: (v: number) => v.toFixed(2) },
];

/** Дашборд (SPEC §10.1): цифры кликабельны — ведут на отфильтрованный список. */
export function DashboardPage() {
  const [days, setDays] = useState(30);
  const query = useDashboard(days);
  const perms = usePermissionsQuery();
  const client = useQueryClient();
  const refresh = useMutation({
    mutationFn: refreshDashboard,
    onSuccess: () => client.invalidateQueries({ queryKey: ["dashboard"] }),
  });
  const data = query.data;
  const controls = (
    <Space wrap>
      <Typography.Text>{t.dashboard.period}</Typography.Text>
      <Segmented value={days} options={[7, 30, 90]} onChange={setDays} />
      {data?.refreshed_at ? (
        <Typography.Text type="secondary">
          {t.dashboard.refreshed}: {formatDateTime(data.refreshed_at)}
        </Typography.Text>
      ) : null}
      {allowed(perms.data, "settings", "write") ? (
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
  );
  return (
    <>
      <PageHeader title={t.page.dashboard} extra={controls} />
      <PageState query={query} ready={Boolean(data)}>
        {data ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Tiles data={data} days={days} />
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}>
                <Card size="small" title={t.dashboard.funnel}>
                  <Funnel funnel={data.funnel} />
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
                columns={DAILY_COLUMNS}
              />
            </Card>
          </Space>
        ) : null}
      </PageState>
    </>
  );
}
