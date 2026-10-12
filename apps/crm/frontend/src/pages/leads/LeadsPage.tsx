import { FilterOutlined } from "@ant-design/icons";
import {
  Button,
  DatePicker,
  Drawer,
  Flex,
  Grid,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import type { LeadOut } from "../../api/generated/model";
import { useLeads } from "../../api/queries";
import { LeadLink } from "../../components/EntityLink";
import { Owner } from "../../components/Owner";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { LangTag, PriorityTag, StageBadge } from "../../components/StageBadge";
import { languageOptions, stageOptions } from "../../domain/labels";
import {
  activeFilterCount,
  LEAD_SORTS,
  LEADS_PAGE,
  type LeadFilters,
  toListParams,
} from "../../hooks/leadFilters";
import { useLeadFilters } from "../../hooks/useLeadFilters";
import { t } from "../../i18n/ru";
import { DATE_FORMAT, formatWhen } from "../../lib/time";
import "../../styles/workspace.css";
import "../pages.css";
import { LeadCards } from "./LeadCards";

type Update = (patch: Partial<LeadFilters>) => void;
type FilterProps = { filters: LeadFilters; update: Update };

/** Поиск, стадия, ответственный. У каждого поля — доступное имя (axe `label`, WCAG 3.3.2). */
function MainFilters({ filters, update }: FilterProps) {
  return (
    <>
      <Input.Search
        allowClear
        key={filters.q ?? ""}
        aria-label={t.leads.search}
        defaultValue={filters.q}
        placeholder={t.leads.search}
        onSearch={(q) => {
          update({ q: q || undefined });
        }}
        style={{ width: 240 }}
      />
      <Select
        allowClear
        aria-label={t.leads.stage}
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
        aria-label={t.leads.owner}
        placeholder={t.leads.owner}
        style={{ width: 176 }}
        value={filters.owner}
        options={[
          { value: "me", label: t.leads.ownerMe },
          { value: "none", label: t.leads.ownerNone },
        ]}
        onChange={(owner?: string) => {
          update({ owner });
        }}
      />
    </>
  );
}

/** Язык, оценка, период и сортировка. */
function MoreFilters({ filters, update }: FilterProps) {
  return (
    <>
      <Select
        allowClear
        aria-label={t.leads.language}
        placeholder={t.leads.language}
        style={{ width: 176 }}
        value={filters.language}
        options={languageOptions()}
        onChange={(language?: string) => {
          update({ language });
        }}
      />
      <InputNumber
        min={0}
        max={100}
        aria-label={t.leads.minScore}
        placeholder={t.leads.minScore}
        style={{ width: 128 }}
        value={filters.min_score ?? null}
        onChange={(value) => {
          update({ min_score: value ?? undefined });
        }}
      />
      <DatePicker.RangePicker
        format={DATE_FORMAT}
        aria-label={t.leads.periodLabel}
        placeholder={t.leads.period}
        value={filters.from && filters.to ? [dayjs(filters.from), dayjs(filters.to)] : null}
        onChange={(range) => {
          update({ from: range?.[0]?.format("YYYY-MM-DD"), to: range?.[1]?.format("YYYY-MM-DD") });
        }}
      />
      <Select
        aria-label={t.leads.sort}
        style={{ width: 224 }}
        value={filters.sort ?? "last_message"}
        options={LEAD_SORTS.map((v) => ({ value: v, label: t.leads.sorts[v] ?? v }))}
        onChange={(sort: string) => {
          update({ sort: sort === "last_message" ? undefined : sort });
        }}
      />
    </>
  );
}

function ResetButton({ filters, reset }: { filters: LeadFilters; reset: () => void }) {
  if (!activeFilterCount(filters)) return null;
  return (
    <Button type="link" onClick={reset}>
      {t.leads.reset}
    </Button>
  );
}

type FiltersProps = FilterProps & { reset: () => void };

function Filters(props: FiltersProps) {
  return (
    <Space wrap role="search" aria-label={t.leads.filters}>
      <MainFilters {...props} />
      <MoreFilters {...props} />
      <ResetButton filters={props.filters} reset={props.reset} />
    </Space>
  );
}

/** Телефон: одна кнопка «Фильтры (n)» и нижняя панель с теми же полями. */
function PhoneFilters(props: FiltersProps) {
  const [open, setOpen] = useState(false);
  const n = activeFilterCount(props.filters);
  return (
    <>
      <Button
        icon={<FilterOutlined />}
        className="filters-button"
        onClick={() => {
          setOpen(true);
        }}
      >
        {n ? t.leads.filtersCount.replace("{n}", String(n)) : t.leads.filtersButton}
      </Button>
      <Drawer
        placement="bottom"
        height="auto"
        open={open}
        title={t.leads.filters}
        onClose={() => {
          setOpen(false);
        }}
        footer={
          <Button
            type="primary"
            block
            onClick={() => {
              setOpen(false);
            }}
          >
            {t.leads.showResults}
          </Button>
        }
      >
        <Flex
          vertical
          gap="small"
          role="search"
          aria-label={t.leads.filters}
          className="drawer-filters"
        >
          <MainFilters {...props} />
          <MoreFilters {...props} />
          <ResetButton filters={props.filters} reset={props.reset} />
        </Flex>
      </Drawer>
    </>
  );
}

const COLUMNS = [
  {
    title: t.leads.name,
    render: (_: unknown, lead: LeadOut) => <LeadLink id={lead.id} name={lead.display_name} />,
  },
  { title: t.leads.stage, render: (_: unknown, l: LeadOut) => <StageBadge stage={l.stage} /> },
  { title: t.leads.score, dataIndex: "score", width: 90 },
  {
    title: t.leads.whoLeads,
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

/** Таблица лидов (SPEC §10.1): фильтры, период и сортировка — в URL; на телефоне — карточки. */
export function LeadsPage() {
  const { filters, update, reset } = useLeadFilters();
  const query = useLeads(toListParams(filters));
  const phone = Grid.useBreakpoint().sm === false;
  const pagination = {
    current: filters.page,
    pageSize: LEADS_PAGE,
    total: query.data?.total ?? 0,
    showSizeChanger: false,
    onChange: (page: number) => {
      update({ page });
    },
  };
  const items = query.data?.items ?? [];
  return (
    <PageBody>
      <PageHeader title={t.page.leads} />
      {phone ? (
        <PhoneFilters filters={filters} update={update} reset={reset} />
      ) : (
        <Filters filters={filters} update={update} reset={reset} />
      )}
      <PageState query={query} inline>
        {phone ? (
          <LeadCards items={items} loading={query.isLoading} pagination={pagination} />
        ) : (
          <Table<LeadOut>
            rowKey="id"
            loading={query.isLoading}
            dataSource={items}
            scroll={{ x: 720 }}
            pagination={pagination}
            columns={COLUMNS}
          />
        )}
      </PageState>
    </PageBody>
  );
}
