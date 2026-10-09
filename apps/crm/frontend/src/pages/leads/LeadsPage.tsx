import { Input, InputNumber, Select, Space, Table } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link } from "react-router";

import type { LeadOut, ListLeadsParams } from "../../api/generated/model";
import { useLeads } from "../../api/queries";
import { PriorityTag } from "../../components/EscalationReason";
import { Owner } from "../../components/Owner";
import { StageBadge } from "../../components/StageBadge";
import { t } from "../../i18n/ru";
import "../pages.css";

const PAGE = 50;

/** Таблица лидов с фильтрами (SPEC §10.1). */
export function LeadsPage() {
  const [params, setParams] = useState<ListLeadsParams>({ limit: PAGE, offset: 0 });
  const { data, isLoading } = useLeads(params);
  const update = (patch: Partial<ListLeadsParams>) => {
    setParams((current) => ({ ...current, ...patch, offset: 0 }));
  };

  return (
    <>
      <Space wrap className="filters">
        <Input.Search
          allowClear
          placeholder={t.leads.search}
          onSearch={(q) => {
            update({ q: q || null });
          }}
          style={{ width: 240 }}
        />
        <Select
          allowClear
          placeholder={t.leads.stage}
          style={{ width: 180 }}
          options={Object.entries(t.stage).map(([value, label]) => ({ value, label }))}
          onChange={(stage?: string) => {
            update({ stage: stage ?? null });
          }}
        />
        <Select
          allowClear
          placeholder={t.leads.owner}
          style={{ width: 160 }}
          options={[
            { value: "me", label: t.leads.ownerMe },
            { value: "none", label: t.leads.ownerNone },
          ]}
          onChange={(owner?: string) => {
            update({ owner: owner ?? null });
          }}
        />
        <Select
          allowClear
          placeholder={t.leads.language}
          style={{ width: 120 }}
          options={["ru", "uz", "en"].map((value) => ({ value, label: value.toUpperCase() }))}
          onChange={(language?: string) => {
            update({ language: language ?? null });
          }}
        />
        <InputNumber
          min={0}
          max={100}
          placeholder={t.leads.score}
          onChange={(value) => {
            update({ min_score: value ?? null });
          }}
        />
      </Space>
      <Table<LeadOut>
        rowKey="id"
        loading={isLoading}
        dataSource={data?.items ?? []}
        scroll={{ x: 720 }}
        pagination={{
          pageSize: PAGE,
          total: data?.total ?? 0,
          showSizeChanger: false,
          onChange: (page) => {
            setParams((current) => ({ ...current, offset: (page - 1) * PAGE }));
          },
        }}
        columns={[
          {
            title: t.leads.name,
            render: (_, lead) => (
              <Link to={`/leads/${String(lead.id)}`}>
                #{lead.id} · {lead.display_name || t.common.none}
              </Link>
            ),
          },
          { title: t.leads.stage, render: (_, lead) => <StageBadge stage={lead.stage} /> },
          { title: t.leads.score, dataIndex: "score", width: 80 },
          {
            title: t.leads.owner,
            render: (_, lead) => (
              <Space>
                <Owner lead={lead} />
                {lead.escalation ? <PriorityTag priority={lead.escalation.priority} /> : null}
              </Space>
            ),
          },
          { title: t.leads.language, dataIndex: "language", width: 70 },
          { title: t.leads.need, dataIndex: "need_summary", ellipsis: true },
          {
            title: t.leads.lastMessage,
            render: (_, lead) =>
              lead.last_lead_msg_at
                ? dayjs(lead.last_lead_msg_at).format("DD.MM HH:mm")
                : t.common.none,
          },
        ]}
      />
    </>
  );
}
