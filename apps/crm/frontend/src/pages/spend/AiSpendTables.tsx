/**
 * Таблицы вкладки «Ансамбль» (M3-CRM-09): по дням с колонками систем и деградаций и разрезы по
 * системе, функции и модели. На телефоне — только ключевые колонки, без горизонтальной прокрутки.
 */
import { Card, Grid, Segmented, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";

import type { AiSpendReport, AiSpendRow } from "../../api/generated/model";
import { useAiSpend } from "../../api/spendQueries";
import { PageState } from "../../components/PageState";
import {
  SLICE_GROUPS,
  type SliceGroup,
  dayColumnsSystems,
  daysNewestFirst,
  sliceLabel,
  systemCost,
  systemLabel,
  usdPrecise,
} from "../../domain/aiSpend";
import { t } from "../../i18n/ru";
import { formatNumber } from "../../lib/format";
import { formatDate } from "../../lib/time";

const A = t.aiSpend;

const tokens = (r: AiSpendRow) =>
  `${formatNumber(r.input_tokens)} / ${formatNumber(r.output_tokens)}`;

const common = (phone: boolean): ColumnsType<AiSpendRow> => [
  ...(phone
    ? []
    : [
        { title: A.callsCol, dataIndex: "calls", align: "right" as const, width: 100 },
        { title: A.tokensCol, key: "tokens", align: "right" as const, render: tokens },
      ]),
  {
    title: A.degraded,
    dataIndex: "fallback_calls",
    align: "right",
    width: 120,
    render: (n: number) => <span title={A.degradedHint}>{n}</span>,
  },
];

function dayColumns(rows: AiSpendRow[], phone: boolean): ColumnsType<AiSpendRow> {
  const systems = phone ? [] : dayColumnsSystems(rows);
  return [
    { title: A.day, dataIndex: "key", render: (v: string) => formatDate(v) },
    ...systems.map((s) => ({
      title: systemLabel(s),
      key: s,
      align: "right" as const,
      render: (_: unknown, r: AiSpendRow) => usdPrecise(systemCost(r, s)),
    })),
    { title: A.totalCol, dataIndex: "cost_usd", align: "right", render: usdPrecise },
    ...common(phone),
  ];
}

export function DayTable({ report }: { report: AiSpendReport }) {
  const phone = Grid.useBreakpoint().sm === false;
  return (
    <Card title={A.byDay} size="small">
      <Table
        rowKey="key"
        size="small"
        pagination={{ pageSize: 10, hideOnSinglePage: true }}
        dataSource={daysNewestFirst(report.rows)}
        columns={dayColumns(report.rows, phone)}
      />
    </Card>
  );
}

function sliceColumns(group: SliceGroup, phone: boolean): ColumnsType<AiSpendRow> {
  return [
    { title: A.groups[group], dataIndex: "key", render: (k: string) => sliceLabel(group, k) },
    { title: A.costCol, dataIndex: "cost_usd", align: "right", render: usdPrecise },
    ...(phone
      ? []
      : [{ title: A.failedCol, dataIndex: "failed_calls", align: "right" as const, width: 100 }]),
    ...common(phone),
  ];
}

/** Разрез периода: отдельный запрос с `group` — журнал на бэкенде тот же (кэш 60 с). */
export function Slices({ range }: { range: { from: string; to: string } }) {
  const [group, setGroup] = useState<SliceGroup>("system");
  const phone = Grid.useBreakpoint().sm === false;
  const query = useAiSpend(range, group);
  return (
    <Card
      title={A.slices}
      size="small"
      extra={
        <Segmented<SliceGroup>
          aria-label={A.sliceBy}
          value={group}
          onChange={setGroup}
          options={SLICE_GROUPS.map((g) => ({ value: g, label: A.groups[g] }))}
        />
      }
    >
      <PageState query={query} variant="section">
        <Table
          rowKey="key"
          size="small"
          pagination={false}
          dataSource={query.data?.rows ?? []}
          columns={sliceColumns(group, phone)}
        />
      </PageState>
    </Card>
  );
}
