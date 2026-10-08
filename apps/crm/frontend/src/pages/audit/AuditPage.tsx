import { Input, Select, Space, Table, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { useAudit } from "../../api/adminQueries";
import type { AuditItem, ListAuditParams } from "../../api/generated/model";
import { useUsers } from "../../api/queries";
import { t } from "../../i18n/ru";

const PAGE = 50;

function diff(item: AuditItem): string {
  const before = item.before ?? {};
  const after = item.after ?? {};
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  return keys
    .filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]))
    .map((k) => `${k}: ${JSON.stringify(before[k] ?? null)} → ${JSON.stringify(after[k] ?? null)}`)
    .join("; ");
}

/** Журнал аудита (admin): кто, что, над чем, до/после. */
export function AuditPage() {
  const [params, setParams] = useState<ListAuditParams>({ limit: PAGE, offset: 0 });
  const { data, isLoading } = useAudit(params);
  const users = useUsers();
  const names = new Map((users.data ?? []).map((u) => [u.id, u.full_name]));
  const update = (patch: Partial<ListAuditParams>) => {
    setParams((p) => ({ ...p, ...patch, offset: 0 }));
  };

  return (
    <>
      <Space wrap className="filters">
        <Select
          allowClear
          placeholder={t.audit.actor}
          style={{ width: 200 }}
          options={(users.data ?? []).map((u) => ({ value: u.id, label: u.full_name }))}
          onChange={(v?: number) => {
            update({ actor_user_id: v ?? null });
          }}
        />
        <Input.Search
          allowClear
          placeholder={t.audit.action}
          style={{ width: 200 }}
          onSearch={(v) => {
            update({ action: v || null });
          }}
        />
        <Select
          allowClear
          placeholder={t.audit.entity}
          style={{ width: 160 }}
          options={["lead", "user", "kb_document", "kb_gap", "settings", "product"].map((v) => ({
            value: v,
            label: v,
          }))}
          onChange={(v?: string) => {
            update({ entity_type: v ?? null });
          }}
        />
      </Space>
      <Table<AuditItem>
        rowKey="id"
        size="small"
        loading={isLoading}
        dataSource={data?.items ?? []}
        scroll={{ x: 900 }}
        pagination={{
          pageSize: PAGE,
          total: data?.total ?? 0,
          showSizeChanger: false,
          onChange: (page) => {
            setParams((p) => ({ ...p, offset: (page - 1) * PAGE }));
          },
        }}
        columns={[
          {
            title: t.audit.when,
            dataIndex: "created_at",
            render: (v: string) => dayjs(v).format("DD.MM.YY HH:mm:ss"),
            width: 150,
          },
          {
            title: t.audit.actor,
            render: (_, r) =>
              r.actor_user_id
                ? (names.get(r.actor_user_id) ?? `#${String(r.actor_user_id)}`)
                : r.actor_type,
          },
          { title: t.audit.action, dataIndex: "action" },
          { title: t.audit.entity, render: (_, r) => `${r.entity_type} ${r.entity_id ?? ""}` },
          {
            title: t.audit.changes,
            render: (_, r) => <Typography.Text type="secondary">{diff(r)}</Typography.Text>,
          },
          { title: "IP", dataIndex: "ip", width: 120 },
        ]}
      />
    </>
  );
}
