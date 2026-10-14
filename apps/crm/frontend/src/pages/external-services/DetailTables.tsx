import { Card, Flex, Grid, List, Progress, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { ReactNode } from "react";

import type { IncidentOut, ServiceCheckOut, ServiceDayOut } from "../../api/generated/model";
import { EmptyState } from "../../components/EmptyState";
import { durationFromSeconds, percent } from "../../domain/externalServices";
import { t } from "../../i18n/ru";
import { formatDuration, formatNumber } from "../../lib/format";
import { formatDate, formatDateTime, formatWhen } from "../../lib/time";
import { ServiceStatusTag } from "./parts";

/** Телефон (≤ 575 px): карточки-строки вместо таблиц — без горизонтальной прокрутки (crm-page). */
const usePhone = () => Grid.useBreakpoint().sm === false;

function PhoneList<T>({
  rows,
  rowKey,
  render,
}: {
  rows: T[];
  rowKey: (row: T) => string;
  render: (row: T) => ReactNode;
}) {
  return (
    <List<T>
      size="small"
      dataSource={rows}
      rowKey={rowKey}
      renderItem={(row) => <List.Item>{render(row)}</List.Item>}
    />
  );
}

function Uptime({ uptime }: { uptime: number | null }) {
  const s = t.externalServices.days;
  if (uptime === null) return <Typography.Text type="secondary">{s.noData}</Typography.Text>;
  return (
    <Progress
      percent={Math.round(uptime * 1000) / 10}
      size="small"
      status={uptime < 0.99 ? "exception" : "success"}
      format={() => percent(uptime)}
      aria-label={`${s.uptime}: ${percent(uptime)}`}
    />
  );
}

/** 7 дней: доля исправных проверок полосой и числом (цвет — не единственный признак). */
export function DaysTable({ days }: { days: ServiceDayOut[] }) {
  const s = t.externalServices.days;
  const phone = usePhone();
  const columns: ColumnsType<ServiceDayOut> = [
    { title: s.day, dataIndex: "day", width: 120, render: (day: string) => formatDate(day) },
    {
      title: s.uptime,
      dataIndex: "uptime",
      render: (uptime: number | null) => <Uptime uptime={uptime} />,
    },
    { title: s.failures, dataIndex: "fail", width: 100, align: "right" },
  ];
  return (
    <Card title={s.title}>
      {phone ? (
        <PhoneList
          rows={days}
          rowKey={(d) => d.day}
          render={(d) => (
            <Flex vertical gap={4} className="service-phone-row">
              <Typography.Text strong>
                {formatDate(d.day)} · {s.failures}: {d.fail}
              </Typography.Text>
              <Uptime uptime={d.uptime} />
            </Flex>
          )}
        />
      ) : (
        <Table<ServiceDayOut>
          rowKey="day"
          size="small"
          pagination={false}
          dataSource={days}
          columns={columns}
        />
      )}
    </Card>
  );
}

function CheckResult({ row }: { row: ServiceCheckOut }) {
  const s = t.externalServices.history;
  return (
    <>
      {row.summary}
      {row.error ? (
        <Typography.Text type="secondary" className="service-error">
          {" "}
          ({row.error})
        </Typography.Text>
      ) : null}
      <Typography.Text type="secondary"> · {s.tier[row.tier]}</Typography.Text>
    </>
  );
}

export function HistoryTable({ checks }: { checks: ServiceCheckOut[] }) {
  const s = t.externalServices.history;
  const phone = usePhone();
  const columns: ColumnsType<ServiceCheckOut> = [
    {
      title: s.when,
      dataIndex: "checked_at",
      width: 120,
      className: "nowrap",
      render: (at: string) => formatWhen(at),
    },
    {
      title: s.status,
      dataIndex: "status",
      width: 130,
      render: (status: ServiceCheckOut["status"]) => <ServiceStatusTag status={status} />,
    },
    {
      title: s.latency,
      dataIndex: "latency_ms",
      width: 100,
      align: "right",
      render: (ms: number | null) => (ms === null ? t.common.none : formatNumber(ms)),
    },
    { title: s.result, key: "result", render: (_: unknown, row) => <CheckResult row={row} /> },
  ];
  const key = (row: ServiceCheckOut) => `${row.checked_at}-${row.tier}`;
  let body: ReactNode = <EmptyState compact title={s.empty} />;
  if (checks.length && phone) {
    body = (
      <PhoneList
        rows={checks.slice(0, 30)}
        rowKey={key}
        render={(row) => (
          <Flex vertical gap={4} className="service-phone-row">
            <Flex gap="small" align="center" wrap>
              <Typography.Text strong>{formatWhen(row.checked_at)}</Typography.Text>
              <ServiceStatusTag status={row.status} />
            </Flex>
            <Typography.Text>
              <CheckResult row={row} />
            </Typography.Text>
          </Flex>
        )}
      />
    );
  } else if (checks.length) {
    body = (
      <Table<ServiceCheckOut>
        rowKey={key}
        size="small"
        pagination={{ pageSize: 20, showSizeChanger: false }}
        dataSource={checks}
        columns={columns}
      />
    );
  }
  return <Card title={s.title}>{body}</Card>;
}

function IncidentWhat({ row }: { row: IncidentOut }) {
  const s = t.externalServices.incident;
  return (
    <>
      {row.summary}
      {row.last_error ? (
        <Typography.Text type="secondary" className="service-error">
          {" "}
          ({s.lastError}: {row.last_error})
        </Typography.Text>
      ) : null}
    </>
  );
}

const ended = (at: string | null) =>
  at ? (
    formatDateTime(at)
  ) : (
    <Typography.Text type="danger">{t.externalServices.incident.ongoing}</Typography.Text>
  );

const lasted = (sec: number | null) =>
  sec === null ? t.common.none : formatDuration(durationFromSeconds(sec));

export function IncidentsTable({ incidents }: { incidents: IncidentOut[] }) {
  const s = t.externalServices.incident;
  const phone = usePhone();
  const columns: ColumnsType<IncidentOut> = [
    {
      title: s.started,
      dataIndex: "started_at",
      width: 150,
      className: "nowrap",
      render: (at: string) => formatDateTime(at),
    },
    { title: s.ended, dataIndex: "ended_at", width: 150, className: "nowrap", render: ended },
    { title: s.duration, dataIndex: "duration_s", width: 120, render: lasted },
    { title: s.what, key: "what", render: (_: unknown, row) => <IncidentWhat row={row} /> },
    {
      title: s.alerted,
      dataIndex: "alerted",
      width: 110,
      render: (alerted: boolean) => (alerted ? s.alertedYes : s.alertedNo),
    },
  ];
  let body: ReactNode = <EmptyState compact title={s.empty} />;
  if (incidents.length && phone) {
    body = (
      <PhoneList
        rows={incidents}
        rowKey={(row) => String(row.id)}
        render={(row) => (
          <Flex vertical gap={4} className="service-phone-row">
            <Typography.Text strong>
              {formatDateTime(row.started_at)} — {ended(row.ended_at)}
            </Typography.Text>
            <Typography.Text type="secondary">
              {s.duration}: {lasted(row.duration_s)} · {s.alerted}:{" "}
              {row.alerted ? s.alertedYes : s.alertedNo}
            </Typography.Text>
            <Typography.Text>
              <IncidentWhat row={row} />
            </Typography.Text>
          </Flex>
        )}
      />
    );
  } else if (incidents.length) {
    body = (
      <Table<IncidentOut>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={incidents}
        columns={columns}
      />
    );
  }
  return <Card title={s.title}>{body}</Card>;
}
