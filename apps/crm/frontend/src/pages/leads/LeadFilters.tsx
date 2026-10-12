import { DownOutlined, FilterOutlined } from "@ant-design/icons";
import {
  Badge,
  Button,
  DatePicker,
  Drawer,
  Flex,
  Input,
  InputNumber,
  Popover,
  Select,
  Space,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { languageOptions, stageOptions } from "../../domain/labels";
import {
  activeFilterCount,
  hiddenFilterCount,
  LEAD_SORTS,
  type LeadFilters,
} from "../../hooks/leadFilters";
import { t } from "../../i18n/ru";
import { rangePresets } from "../../lib/datePresets";
import { DATE_FORMAT } from "../../lib/time";

type Update = (patch: Partial<LeadFilters>) => void;
type FilterProps = { filters: LeadFilters; update: Update };
export type FiltersProps = FilterProps & { reset: () => void };

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
        aria-label={t.leads.whoLeads}
        placeholder={t.leads.whoLeads}
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

/** Язык, оценка, период и сортировка — реже нужные, поэтому за кнопкой «Ещё фильтры». */
function MoreFilters({ filters, update }: FilterProps) {
  return (
    <>
      <Select
        allowClear
        aria-label={t.leads.language}
        placeholder={t.leads.language}
        style={{ width: "100%" }}
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
        style={{ width: "100%" }}
        value={filters.min_score ?? null}
        onChange={(value) => {
          update({ min_score: value ?? undefined });
        }}
      />
      <DatePicker.RangePicker
        format={DATE_FORMAT}
        aria-label={t.leads.periodLabel}
        placeholder={t.leads.period}
        presets={rangePresets()}
        style={{ width: "100%" }}
        value={filters.from && filters.to ? [dayjs(filters.from), dayjs(filters.to)] : null}
        onChange={(range) => {
          update({ from: range?.[0]?.format("YYYY-MM-DD"), to: range?.[1]?.format("YYYY-MM-DD") });
        }}
      />
      <Select
        aria-label={t.leads.sort}
        style={{ width: "100%" }}
        value={filters.sort ?? "last_message"}
        options={LEAD_SORTS.map((v) => ({
          value: v,
          label: `${t.leads.sort}: ${t.leads.sorts[v] ?? v}`,
        }))}
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

/** Кнопка «Ещё фильтры» с числом включённых скрытых фильтров и маленькой формой в `Popover`. */
function MoreFiltersButton(props: FilterProps) {
  const n = hiddenFilterCount(props.filters);
  return (
    <Popover
      trigger="click"
      placement="bottomLeft"
      content={
        <Flex vertical gap="small" className="more-filters">
          <MoreFilters {...props} />
        </Flex>
      }
    >
      <Badge count={n} size="small">
        <Button
          icon={<FilterOutlined />}
          aria-label={n ? t.leads.moreFiltersCount.replace("{n}", String(n)) : t.leads.moreFilters}
        >
          <Space size={4}>
            {t.leads.moreFilters}
            <DownOutlined aria-hidden />
          </Space>
        </Button>
      </Badge>
    </Popover>
  );
}

/** Десктоп: фильтры в одну строку — поиск, стадия, «Кто ведёт», «Ещё фильтры», «Сбросить». */
export function Filters(props: FiltersProps) {
  return (
    <Space wrap role="search" aria-label={t.leads.filters}>
      <MainFilters {...props} />
      <MoreFiltersButton {...props} />
      <ResetButton filters={props.filters} reset={props.reset} />
    </Space>
  );
}

/** Телефон: одна кнопка «Фильтры (n)» и нижняя панель с теми же полями. */
export function PhoneFilters(props: FiltersProps) {
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
