import { ArrowDownOutlined, ArrowRightOutlined, ArrowUpOutlined } from "@ant-design/icons";
import { Card, Collapse, Flex, Statistic, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Link } from "react-router";

import type {
  DailyStat,
  ManagerStat,
  PermissionsResponse,
  SlaStat,
} from "../../api/generated/model";
import { type Tile, tileLink, visibleTiles } from "../../domain/dashboard";
import type { Trend } from "../../domain/dashboardCharts";
import { EmptyState } from "../../components/EmptyState";
import { t } from "../../i18n/ru";
import { formatDuration, formatUsd } from "../../lib/format";
import { formatDate } from "../../lib/time";

const TREND_ICON = { up: <ArrowUpOutlined aria-hidden />, down: <ArrowDownOutlined aria-hidden /> };

/** Тренд нейтральным цветом: рост лидов — хорошо, рост времени до «Забрать» — плохо. */
function TrendLine({ trend }: { trend: Trend | null | undefined }) {
  if (!trend) return null;
  return (
    <Typography.Text type="secondary" className="metric-hint">
      {trend.direction === "flat" ? null : TREND_ICON[trend.direction]} {trend.text}
    </Typography.Text>
  );
}

function TileCard({ tile, link, primary }: { tile: Tile; link: string | null; primary: boolean }) {
  const card = (
    <Card
      size="small"
      className={`metric-card${primary ? " metric-card--primary" : ""}`}
      hoverable={Boolean(link)}
    >
      <Statistic
        title={tile.title}
        value={tile.value}
        suffix={link ? <ArrowRightOutlined aria-hidden className="metric-arrow" /> : null}
      />
      <Flex vertical>
        {tile.hint ? (
          <Typography.Text type="secondary" className="metric-hint">
            {tile.hint}
          </Typography.Text>
        ) : null}
        <TrendLine trend={tile.trend} />
      </Flex>
    </Card>
  );
  if (!link) return card;
  return (
    <Link to={link} className="metric-card--link">
      {card}
    </Link>
  );
}

/** Плитки: ссылка — только если у роли есть доступ к разделу (иначе 403 — тупик). */
export function Tiles({
  tiles,
  perms,
  primary,
}: {
  tiles: Tile[];
  perms: PermissionsResponse | undefined;
  primary: boolean;
}) {
  return (
    <div className={primary ? "metric-grid metric-grid--primary" : "metric-grid"}>
      {visibleTiles(tiles, perms).map((tile) => (
        <TileCard
          key={tile.key}
          tile={tile}
          link={tileLink(tile.target, perms)}
          primary={primary}
        />
      ))}
    </div>
  );
}

const C = t.charts;
const MANAGER_COLUMNS: ColumnsType<ManagerStat> = [
  { title: C.manager, dataIndex: "name" },
  { title: C.mTaken, dataIndex: "taken", align: "right" },
  {
    title: C.mMedian,
    dataIndex: "median_take_minutes",
    align: "right",
    render: (v: number | null) => formatDuration(v),
  },
  { title: C.mWon, dataIndex: "won", align: "right" },
  { title: C.mActive, dataIndex: "active_leads", align: "right" },
];

function slaText(sla: SlaStat | null | undefined): { value: string; hint: string | null } {
  if (!sla || sla.share === null) {
    return { value: t.common.none, hint: null };
  }
  return {
    value: `${String(Math.round(sla.share * 100))}%`,
    hint: C.slaHint.replace("{met}", String(sla.met)).replace("{due}", String(sla.due)),
  };
}

/** Менеджеры за период и доля передач, забранных в срок SLA (SPEC §10.1). */
export function ManagersCard({
  managers,
  sla,
}: {
  managers: ManagerStat[];
  sla: SlaStat | null | undefined;
}) {
  const s = slaText(sla);
  return (
    <Card size="small" title={<h3 className="card-heading">{C.managers}</h3>}>
      <Flex vertical gap="small">
        <div>
          <Statistic title={C.sla} value={s.value} />
          {s.hint ? (
            <Typography.Text type="secondary" className="metric-hint">
              {s.hint}
            </Typography.Text>
          ) : null}
        </div>
        {managers.length ? (
          <Table<ManagerStat>
            rowKey="user_id"
            pagination={false}
            dataSource={managers}
            columns={MANAGER_COLUMNS}
          />
        ) : (
          <EmptyState compact title={C.managersEmpty} />
        )}
      </Flex>
    </Card>
  );
}

const DAILY_COLUMNS = [
  { title: t.dashboard.day, dataIndex: "day", render: (v: string) => formatDate(v) },
  { title: t.dashboard.leads, dataIndex: "leads_created" },
  { title: t.dashboard.escalations, dataIndex: "escalations" },
  { title: t.dashboard.taken, dataIndex: "taken" },
  { title: t.dashboard.won, dataIndex: "won" },
  { title: t.dashboard.lost, dataIndex: "lost" },
  { title: t.dashboard.cost, dataIndex: "cost_usd", render: (v: number) => formatUsd(v) },
];

/** Таблица по дням — свёрнута: те же числа, что на графиках, для точного просмотра. */
export function Daily({ daily, withCost }: { daily: DailyStat[]; withCost: boolean }) {
  return (
    <Collapse
      items={[
        {
          key: "daily",
          label: t.dashboard.daily,
          children: (
            <Table<DailyStat>
              rowKey="day"
              scroll={{ x: 700 }}
              pagination={{ pageSize: 10 }}
              dataSource={[...daily].reverse()}
              columns={
                withCost ? DAILY_COLUMNS : DAILY_COLUMNS.filter((c) => c.dataIndex !== "cost_usd")
              }
            />
          ),
        },
      ]}
    />
  );
}
