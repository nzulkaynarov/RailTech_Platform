import { ArrowRightOutlined } from "@ant-design/icons";
import { Card, Col, Collapse, Progress, Row, Space, Statistic, Table, Typography } from "antd";
import { Link } from "react-router";

import type { DailyStat, PermissionsResponse } from "../../api/generated/model";
import { StageBadge } from "../../components/StageBadge";
import { leadsPath, reasonBars, type Tile, tileLink, visibleTiles } from "../../domain/dashboard";
import { reasonLabel, STAGE_ORDER } from "../../domain/labels";
import { t } from "../../i18n/ru";
import { formatNumber, formatUsd } from "../../lib/format";
import { formatDate } from "../../lib/time";

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

/** Передачи по причинам: один нейтральный цвет, без «успешного» зелёного у максимума. */
export function Bars({ data }: { data: Record<string, number> }) {
  const bars = reasonBars(data);
  if (!bars.length)
    return <Typography.Text type="secondary">{t.dashboard.reasonsEmpty}</Typography.Text>;
  return (
    <Space direction="vertical" className="bar-row">
      {bars.map((bar) => (
        <div key={bar.code}>
          <Typography.Text id={`reason-${bar.code}`}>{reasonLabel(bar.code)}</Typography.Text>
          <Progress
            aria-labelledby={`reason-${bar.code}`}
            percent={bar.percent}
            status="normal"
            strokeColor="var(--ant-color-primary)"
            format={() => bar.value}
          />
        </div>
      ))}
    </Space>
  );
}

/** Все стадии, включая нулевые: пустая стадия — тоже сигнал. Итог — отдельной строкой. */
export function Funnel({ funnel }: { funnel: Record<string, number> }) {
  const rows = STAGE_ORDER.map((stage) => ({ stage, n: funnel[stage] ?? 0 }));
  const total = Object.values(funnel).reduce((sum, n) => sum + n, 0);
  return (
    <Table
      summary={() => (
        <Table.Summary.Row>
          <Table.Summary.Cell index={0}>
            <Typography.Text strong>{t.dashboard.funnelTotal}</Typography.Text>
          </Table.Summary.Cell>
          <Table.Summary.Cell index={1} align="right">
            <Typography.Text strong>{formatNumber(total)}</Typography.Text>
          </Table.Summary.Cell>
        </Table.Summary.Row>
      )}
      size="small"
      pagination={false}
      showHeader={false}
      rowKey="stage"
      dataSource={rows}
      columns={[
        {
          render: (_, r) => (
            <Link to={leadsPath({ stage: r.stage })}>
              <StageBadge stage={r.stage} />
            </Link>
          ),
        },
        { dataIndex: "n", align: "right", render: (n: number) => formatNumber(n) },
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
  { title: t.dashboard.cost, dataIndex: "cost_usd", render: (v: number) => formatUsd(v) },
];

/** Таблица по дням — свёрнута: вторична к плиткам и воронке. */
export function Daily({ daily }: { daily: DailyStat[] }) {
  return (
    <Collapse
      items={[
        {
          key: "daily",
          label: t.dashboard.daily,
          children: (
            <Table<DailyStat>
              size="small"
              rowKey="day"
              scroll={{ x: 700 }}
              pagination={{ pageSize: 10 }}
              dataSource={[...daily].reverse()}
              columns={DAILY_COLUMNS}
            />
          ),
        },
      ]}
    />
  );
}

export function Panels({
  funnel,
  reasons,
}: {
  funnel: Record<string, number>;
  reasons: Record<string, number>;
}) {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card size="small" title={<h3 className="card-heading">{t.dashboard.funnel}</h3>}>
          <Typography.Paragraph type="secondary">{t.dashboard.funnelHint}</Typography.Paragraph>
          <Funnel funnel={funnel} />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card size="small" title={<h3 className="card-heading">{t.dashboard.reasons}</h3>}>
          <Bars data={reasons} />
        </Card>
      </Col>
    </Row>
  );
}
