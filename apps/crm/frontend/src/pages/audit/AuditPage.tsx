import { DatePicker, Descriptions, Flex, Select, Switch, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";

import { useAudit } from "../../api/adminQueries";
import type { AuditItem, ListAuditParams } from "../../api/generated/model";
import { useUsers } from "../../api/queries";
import { EntityLink } from "../../components/EntityLink";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { type AuditContext, auditChanges, entityText } from "../../domain/audit";
import { actorLabel, auditActionLabel, ENTITY_TYPES, entityLabel } from "../../domain/labels";
import { useProductNames } from "../../hooks/useProductNames";
import { t } from "../../i18n/ru";
import { DATE_FORMAT, formatDateTime, TIMEZONE } from "../../lib/time";
import "../admin.css";

const PAGE = 50;
/** Входы (и неудачные попытки) по умолчанию скрыты — они забивают журнал изменений. */
const HIDE_LOGINS = ["auth.login"];
const ACTION_OPTIONS = Object.keys(t.labels.auditAction).map((value) => ({
  value,
  label: auditActionLabel(value),
}));
const ENTITY_OPTIONS = ENTITY_TYPES.map((v) => ({ value: v, label: entityLabel(v) }));

type Update = (patch: Partial<ListAuditParams>) => void;
type Option = { value: number; label: string };

/** Начало дня по Ташкенту (ISO с поясом) — для фильтра API. */
const dayStart = (day: Dayjs): string => dayjs.tz(day.format("YYYY-MM-DD"), TIMEZONE).format();

/** Период: с начала первого дня до конца последнего (по Ташкенту). */
function periodPatch(range: [Dayjs | null, Dayjs | null] | null): Partial<ListAuditParams> {
  const [from, to] = range ?? [null, null];
  return {
    created_from: from ? dayStart(from) : null,
    created_to: to ? dayStart(to.add(1, "day")) : null,
  };
}

function Filters({ update, users }: { update: Update; users: Option[] }) {
  return (
    <Flex wrap gap="small">
      <Select
        allowClear
        showSearch
        optionFilterProp="label"
        aria-label={t.audit.actor}
        placeholder={t.audit.allActors}
        className="filter-md"
        options={users}
        onChange={(v?: number) => {
          update({ actor_user_id: v ?? null });
        }}
      />
      <Select
        allowClear
        showSearch
        optionFilterProp="label"
        aria-label={t.audit.action}
        placeholder={t.audit.allActions}
        className="filter-lg"
        options={ACTION_OPTIONS}
        onChange={(v?: string) => {
          update({ action: v ?? null });
        }}
      />
      <Select
        allowClear
        aria-label={t.audit.entity}
        placeholder={t.audit.allEntities}
        className="filter-md"
        options={ENTITY_OPTIONS}
        onChange={(v?: string) => {
          update({ entity_type: v ?? null });
        }}
      />
      <label className="audit-logins">
        <Switch
          size="small"
          onChange={(on) => {
            update({ exclude_actions: on ? null : HIDE_LOGINS });
          }}
        />{" "}
        {t.auditUi.showLogins}
      </label>
      <DatePicker.RangePicker
        className="filter-range"
        aria-label={t.audit.period}
        format={DATE_FORMAT}
        onChange={(range) => {
          update(periodPatch(range));
        }}
      />
    </Flex>
  );
}

function actorText(r: AuditItem, ctx: AuditContext): string {
  if (!r.actor_user_id) return actorLabel(r.actor_type);
  return r.actor_name ?? ctx.userName(r.actor_user_id) ?? `#${String(r.actor_user_id)}`;
}

/** Одна строка на запись: когда · кто · действие · объект · IP; изменения — в раскрытии. */
function columns(ctx: AuditContext): ColumnsType<AuditItem> {
  return [
    {
      title: t.audit.when,
      dataIndex: "created_at",
      className: "nowrap",
      width: 140,
      render: (v: string) => formatDateTime(v),
    },
    { title: t.audit.actor, width: 180, ellipsis: true, render: (_, r) => actorText(r, ctx) },
    { title: t.audit.action, ellipsis: true, render: (_, r) => auditActionLabel(r.action) },
    {
      title: t.audit.entity,
      ellipsis: true,
      width: 220,
      render: (_, r) => (
        <EntityLink type={r.entity_type} id={r.entity_id}>
          {entityText(r.entity_type, r.entity_id, ctx)}
        </EntityLink>
      ),
    },
    { title: t.audit.ip, dataIndex: "ip", className: "nowrap", width: 130 },
  ];
}

/** «Изменения» записи: поле — «до → после», по строке на поле. */
function Changes({ item, ctx }: { item: AuditItem; ctx: AuditContext }) {
  const changes = auditChanges(item, ctx);
  return (
    <Descriptions
      size="small"
      column={1}
      title={t.audit.changes}
      items={changes.map((c, i) => ({
        key: String(i),
        label: c.field,
        children: c.before === undefined ? c.after : `${c.before} → ${c.after}`,
      }))}
    />
  );
}

/** Журнал аудита (admin): кто, что, над чем, до/после — словами, со ссылкой на объект. */
export function AuditPage() {
  const [params, setParams] = useState<ListAuditParams>({
    limit: PAGE,
    offset: 0,
    exclude_actions: HIDE_LOGINS,
  });
  const query = useAudit(params);
  const users = useUsers();
  const productName = useProductNames();
  const names = new Map((users.data ?? []).map((u) => [u.id, u.full_name]));
  const ctx: AuditContext = { userName: (id) => names.get(id), productName };
  const update: Update = (patch) => {
    setParams((p) => ({ ...p, ...patch, offset: 0 }));
  };
  return (
    <PageBody>
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
          sticky
          scroll={{ x: 760 }}
          expandable={{
            rowExpandable: (r) => auditChanges(r, ctx).length > 0,
            expandedRowRender: (r) => <Changes item={r} ctx={ctx} />,
          }}
          pagination={{
            pageSize: PAGE,
            total: query.data?.total ?? 0,
            showSizeChanger: false,
            onChange: (page) => {
              setParams((p) => ({ ...p, offset: (page - 1) * PAGE }));
            },
          }}
          columns={columns(ctx)}
        />
      </PageState>
    </PageBody>
  );
}
