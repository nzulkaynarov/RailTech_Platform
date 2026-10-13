import { Grid, Table } from "antd";
import type { ColumnsType, TableProps } from "antd/es/table";
import { useState } from "react";

import type { LeadOut } from "../../api/generated/model";
import { useLeads, useMe, usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { LeadLink } from "../../components/EntityLink";
import { ExportCsvButton } from "../../components/ExportCsvButton";
import { LeadPreviewDrawer } from "../../components/LeadPreviewDrawer";
import { Owner } from "../../components/Owner";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { LangTag, PriorityTag, StageBadge } from "../../components/StageBadge";
import {
  exportParams,
  type LeadFilters,
  LEADS_PAGE,
  sortFromHeader,
  sortOrderOf,
  toListParams,
} from "../../hooks/leadFilters";
import { useLeadFilters } from "../../hooks/useLeadFilters";
import { t } from "../../i18n/ru";
import { isRowClick } from "../../lib/rowClick";
import { formatWhen } from "../../lib/time";
import "../../styles/workspace.css";
import "../pages.css";
import { LeadCards } from "./LeadCards";
import { Filters, PhoneFilters } from "./LeadFilters";

/**
 * Колонки с шириной: приоритет — отдельной узкой колонкой, а не тегом в «Кто ведёт».
 * «Оценка» и «Последнее сообщение» сортируются кликом по заголовку — на сервере (`sort` в URL),
 * только по убыванию, как умеет API; «по дате создания» — в «Ещё фильтры».
 */
const columns = (sort: LeadFilters["sort"]): ColumnsType<LeadOut> => [
  {
    title: t.leads.name,
    width: 180,
    ellipsis: true,
    render: (_: unknown, lead) => <LeadLink id={lead.id} name={lead.display_name} />,
  },
  {
    title: t.leads.stage,
    width: 130,
    render: (_: unknown, l) => <StageBadge stage={l.stage} />,
  },
  {
    title: t.leads.priority,
    width: 100,
    render: (_: unknown, l) =>
      l.escalation ? <PriorityTag priority={l.escalation.priority} /> : null,
  },
  {
    title: t.leads.score,
    key: "score",
    dataIndex: "score",
    width: 88,
    align: "right",
    sorter: true,
    sortDirections: ["descend"],
    sortOrder: sortOrderOf("score", sort),
  },
  {
    title: t.leads.whoLeads,
    width: 190,
    ellipsis: true,
    render: (_: unknown, lead) => <Owner lead={lead} />,
  },
  {
    title: t.leads.language,
    width: 64,
    render: (_: unknown, l) => <LangTag language={l.language} />,
  },
  { title: t.leads.need, dataIndex: "need_summary", ellipsis: true },
  {
    title: t.leads.lastMessage,
    key: "last_message",
    width: 184,
    sorter: true,
    sortDirections: ["descend"],
    sortOrder: sortOrderOf("last_message", sort),
    render: (_: unknown, l) =>
      l.last_lead_msg_at ? formatWhen(l.last_lead_msg_at) : t.common.none,
  },
];

/**
 * Таблица лидов (SPEC §10.1, UX волна 2): фильтры в одну строку, редкие — в «Ещё фильтры»;
 * всё — в URL. Клик по строке — краткая сводка справа; на телефоне — карточки.
 */
export function LeadsPage() {
  const { filters, update, reset } = useLeadFilters();
  const query = useLeads(toListParams(filters));
  const phone = Grid.useBreakpoint().sm === false;
  const me = useMe();
  const canTake = allowed(usePermissionsQuery().data, "leads", "take") && Boolean(me.data);
  const [preview, setPreview] = useState<number | null>(null);
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
  const onChange: TableProps<LeadOut>["onChange"] = (_page, _filters, sorter, extra) => {
    if (extra.action === "sort" && !Array.isArray(sorter)) update({ sort: sortFromHeader(sorter) });
  };
  return (
    <PageBody>
      <PageHeader
        title={t.page.leads}
        extra={<ExportCsvButton target={{ entity: "leads", params: exportParams(filters) }} />}
      />
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
            sticky
            tableLayout="fixed"
            loading={query.isLoading}
            dataSource={items}
            scroll={{ x: 1040 }}
            pagination={pagination}
            columns={columns(filters.sort)}
            onChange={onChange}
            rowClassName="lead-row"
            onRow={(lead) => ({
              onClick: (event) => {
                if (isRowClick(event.target)) setPreview(lead.id);
              },
            })}
          />
        )}
      </PageState>
      <LeadPreviewDrawer
        leadId={preview}
        canTake={canTake}
        onClose={() => {
          setPreview(null);
        }}
      />
    </PageBody>
  );
}
