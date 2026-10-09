import { Select, Space, Table, Typography } from "antd";
import { useState } from "react";

import { useAudit } from "../../api/adminQueries";
import type { AuditItem, ListAuditParams } from "../../api/generated/model";
import { useUsers } from "../../api/queries";
import { EntityLink } from "../../components/EntityLink";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { auditDiff } from "../../domain/audit";
import { actorLabel, auditActionLabel, ENTITY_TYPES, entityLabel } from "../../domain/labels";
import { t } from "../../i18n/ru";
import { formatDateTime } from "../../lib/time";

const PAGE = 50;
const ACTION_OPTIONS = Object.keys(t.labels.auditAction).map((value) => ({
  value,
  label: auditActionLabel(value),
}));

type Update = (patch: Partial<ListAuditParams>) => void;

function Filters({ update, users }: { update: Update; users: { value: number; label: string }[] }) {
  return (
    <Space wrap className="filters">
      <Select
        allowClear
        showSearch
        optionFilterProp="label"
        placeholder={t.audit.actor}
        style={{ width: 200 }}
        options={users}
        onChange={(v?: number) => {
          update({ actor_user_id: v ?? null });
        }}
      />
      <Select
        allowClear
        showSearch
        optionFilterProp="label"
        placeholder={t.audit.action}
        style={{ width: 240 }}
        options={ACTION_OPTIONS}
        onChange={(v?: string) => {
          update({ action: v ?? null });
        }}
      />
      <Select
        allowClear
        placeholder={t.audit.entity}
        style={{ width: 220 }}
        options={ENTITY_TYPES.map((v) => ({ value: v, label: entityLabel(v) }))}
        onChange={(v?: string) => {
          update({ entity_type: v ?? null });
        }}
      />
    </Space>
  );
}

/** Журнал аудита (admin): кто, что, над чем, до/после — словами, со ссылкой на объект. */
export function AuditPage() {
  const [params, setParams] = useState<ListAuditParams>({ limit: PAGE, offset: 0 });
  const query = useAudit(params);
  const users = useUsers();
  const names = new Map((users.data ?? []).map((u) => [u.id, u.full_name]));
  const update: Update = (patch) => {
    setParams((p) => ({ ...p, ...patch, offset: 0 }));
  };
  return (
    <>
      <PageHeader title={t.page.audit} />
      <Filters
        update={update}
        users={(users.data ?? []).map((u) => ({ value: u.id, label: u.full_name }))}
      />
      <PageState query={query} inline>
        <Table<AuditItem>
          rowKey="id"
          size="small"
          loading={query.isLoading}
          dataSource={query.data?.items ?? []}
          scroll={{ x: 900 }}
          pagination={{
            pageSize: PAGE,
            total: query.data?.total ?? 0,
            showSizeChanger: false,
            onChange: (page) => {
              setParams((p) => ({ ...p, offset: (page - 1) * PAGE }));
            },
          }}
          columns={[
            {
              title: t.audit.when,
              dataIndex: "created_at",
              render: (v: string) => formatDateTime(v),
              width: 150,
            },
            {
              title: t.audit.actor,
              render: (_, r) =>
                r.actor_user_id
                  ? (names.get(r.actor_user_id) ?? `#${String(r.actor_user_id)}`)
                  : actorLabel(r.actor_type),
            },
            { title: t.audit.action, render: (_, r) => auditActionLabel(r.action) },
            {
              title: t.audit.entity,
              render: (_, r) => <EntityLink type={r.entity_type} id={r.entity_id} />,
            },
            {
              title: t.audit.changes,
              render: (_, r) => <Typography.Text type="secondary">{auditDiff(r)}</Typography.Text>,
            },
            { title: t.audit.ip, dataIndex: "ip", width: 120 },
          ]}
        />
      </PageState>
    </>
  );
}
