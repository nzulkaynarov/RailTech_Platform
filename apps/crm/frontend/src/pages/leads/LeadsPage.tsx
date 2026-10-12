import { Grid, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
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
import { exportParams, LEADS_PAGE, toListParams } from "../../hooks/leadFilters";
import { useLeadFilters } from "../../hooks/useLeadFilters";
import { t } from "../../i18n/ru";
import { isRowClick } from "../../lib/rowClick";
import { formatWhen } from "../../lib/time";
import "../../styles/workspace.css";
import "../pages.css";
import { LeadCards } from "./LeadCards";
import { Filters, PhoneFilters } from "./LeadFilters";

/** Колонки с шириной: приоритет — отдельной узкой колонкой, а не тегом в «Кто ведёт». */
const COLUMNS: ColumnsType<LeadOut> = [
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
  { title: t.leads.score, dataIndex: "score", width: 72, align: "right" },
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
    width: 140,
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
            size="small"
            sticky
            tableLayout="fixed"
            loading={query.isLoading}
            dataSource={items}
            scroll={{ x: 1040 }}
            pagination={pagination}
            columns={COLUMNS}
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
