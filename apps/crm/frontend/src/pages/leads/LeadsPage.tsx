import { Button, DatePicker, Input, InputNumber, Select, Space, Table } from "antd";
import dayjs from "dayjs";
import { Link } from "react-router";

import type { LeadOut } from "../../api/generated/model";
import { useLeads } from "../../api/queries";
import { Owner } from "../../components/Owner";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { LangTag, PriorityTag, StageBadge } from "../../components/StageBadge";
import { languageOptions, stageOptions } from "../../domain/labels";
import { LEAD_SORTS, LEADS_PAGE, type LeadFilters, toListParams } from "../../hooks/leadFilters";
import { useLeadFilters } from "../../hooks/useLeadFilters";
import { t } from "../../i18n/ru";
import { formatWhen } from "../../lib/time";
import "../pages.css";

type Update = (patch: Partial<LeadFilters>) => void;

function Filters({ filters, update }: { filters: LeadFilters; update: Update }) {
  return (
    <Space wrap className="filters">
      <Input.Search
        allowClear
        key={filters.q ?? ""}
        defaultValue={filters.q}
        placeholder={t.leads.search}
        onSearch={(q) => {
          update({ q: q || undefined });
        }}
        style={{ width: 240 }}
      />
      <Select
        allowClear
        placeholder={t.leads.stage}
        style={{ width: 180 }}
        value={filters.stage}
        options={stageOptions()}
        onChange={(stage?: string) => {
          update({ stage });
        }}
      />
      <Select
        allowClear
        placeholder={t.leads.owner}
        style={{ width: 160 }}
        value={filters.owner}
        options={[
          { value: "me", label: t.leads.ownerMe },
          { value: "none", label: t.leads.ownerNone },
        ]}
        onChange={(owner?: string) => {
          update({ owner });
        }}
      />
      <Select
        allowClear
        placeholder={t.leads.language}
        style={{ width: 170 }}
        value={filters.language}
        options={languageOptions()}
        onChange={(language?: string) => {
          update({ language });
        }}
      />
      <InputNumber
        min={0}
        max={100}
        placeholder={t.leads.score}
        value={filters.min_score ?? null}
        onChange={(value) => {
          update({ min_score: value ?? undefined });
        }}
      />
      <PeriodAndSort filters={filters} update={update} />
    </Space>
  );
}

function PeriodAndSort({ filters, update }: { filters: LeadFilters; update: Update }) {
  return (
    <>
      <DatePicker.RangePicker
        format="DD.MM.YYYY"
        placeholder={t.leads.period}
        value={filters.from && filters.to ? [dayjs(filters.from), dayjs(filters.to)] : null}
        onChange={(range) => {
          update({ from: range?.[0]?.format("YYYY-MM-DD"), to: range?.[1]?.format("YYYY-MM-DD") });
        }}
      />
      <Select
        style={{ width: 220 }}
        value={filters.sort ?? "last_message"}
        options={LEAD_SORTS.map((v) => ({ value: v, label: t.leads.sorts[v] ?? v }))}
        onChange={(sort: string) => {
          update({ sort: sort === "last_message" ? undefined : sort });
        }}
      />
    </>
  );
}

const COLUMNS = [
  {
    title: t.leads.name,
    render: (_: unknown, lead: LeadOut) => (
      <Link to={`/leads/${String(lead.id)}`}>
        #{lead.id} · {lead.display_name || t.common.none}
      </Link>
    ),
  },
  { title: t.leads.stage, render: (_: unknown, l: LeadOut) => <StageBadge stage={l.stage} /> },
  { title: t.leads.score, dataIndex: "score", width: 90 },
  {
    title: t.leads.owner,
    render: (_: unknown, lead: LeadOut) => (
      <Space>
        <Owner lead={lead} />
        {lead.escalation ? <PriorityTag priority={lead.escalation.priority} /> : null}
      </Space>
    ),
  },
  {
    title: t.leads.language,
    width: 80,
    render: (_: unknown, l: LeadOut) => <LangTag language={l.language} />,
  },
  { title: t.leads.need, dataIndex: "need_summary", ellipsis: true },
  {
    title: t.leads.lastMessage,
    render: (_: unknown, l: LeadOut) =>
      l.last_lead_msg_at ? formatWhen(l.last_lead_msg_at) : t.common.none,
  },
];

/** Таблица лидов (SPEC §10.1): фильтры, период и сортировка — в URL. */
export function LeadsPage() {
  const { filters, update, reset } = useLeadFilters();
  const query = useLeads(toListParams(filters));
  return (
    <>
      <PageHeader
        title={t.page.leads}
        extra={
          <Button size="small" onClick={reset}>
            {t.leads.reset}
          </Button>
        }
      />
      <Filters filters={filters} update={update} />
      <PageState query={query} inline>
        <Table<LeadOut>
          rowKey="id"
          loading={query.isLoading}
          dataSource={query.data?.items ?? []}
          scroll={{ x: 720 }}
          pagination={{
            current: filters.page,
            pageSize: LEADS_PAGE,
            total: query.data?.total ?? 0,
            showSizeChanger: false,
            onChange: (page) => {
              update({ page });
            },
          }}
          columns={COLUMNS}
        />
      </PageState>
    </>
  );
}
