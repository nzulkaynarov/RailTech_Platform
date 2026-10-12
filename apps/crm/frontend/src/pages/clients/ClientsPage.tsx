import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Form, Input, Modal, Table } from "antd";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useClients } from "../../api/adminQueries";
import { createClient } from "../../api/generated/crm";
import type { ClientCreate, ClientListItem } from "../../api/generated/model";
import { unwrap } from "../../api/http";
import { usePermissionsQuery, useTeam } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { BooleanTag } from "../../components/BooleanTag";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { segmentLabel } from "../../domain/labels";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { formatWhen } from "../../lib/time";
import "../pages.css";
import "../admin.css";

type TeamMember = { id: number; full_name: string };

function columns(team: readonly TeamMember[]) {
  const ownerName = (id: number | null) =>
    (id !== null ? team.find((m) => m.id === id)?.full_name : undefined) ?? t.common.none;
  return [
    {
      title: t.clients.name,
      render: (_: unknown, c: ClientListItem) => (
        <Link to={`/clients/${String(c.id)}`}>{c.name}</Link>
      ),
    },
    { title: t.clients.inn, dataIndex: "inn", render: (v: string | null) => v ?? t.common.none },
    { title: t.clients.segment, dataIndex: "segment", render: segmentLabel },
    {
      title: t.clients.owner,
      dataIndex: "owner_user_id",
      render: ownerName,
    },
    { title: t.clients.openDeals, dataIndex: "open_deals", align: "right" as const },
    {
      title: t.clients.lastActivity,
      dataIndex: "last_activity_at",
      render: (v: string | null) => (v ? formatWhen(v) : t.common.none),
    },
    {
      title: t.clients.status,
      render: (_: unknown, c: ClientListItem) => (
        <BooleanTag value={c.is_active} yes={t.clients.active} no={t.clients.inactive} />
      ),
    },
  ];
}

function CreateClientDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [form] = Form.useForm<ClientCreate>();
  const navigate = useNavigate();
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const create = useMutation({
    mutationFn: async (values: ClientCreate) => unwrap(await createClient(values)),
    onSuccess: (created, values) => {
      onClose();
      void message.success(t.clients.created.replace("{name}", values.name));
      void client.invalidateQueries({ queryKey: ["clients"] });
      void navigate(`/clients/${String(created.id)}`);
    },
    onError: useApiErrorToast(),
  });
  return (
    <Modal
      open={open}
      title={t.clients.create}
      confirmLoading={create.isPending}
      destroyOnHidden
      onCancel={onClose}
      onOk={() => {
        form.submit();
      }}
      okText={t.clients.createConfirm}
      cancelText={t.actions.cancel}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={(v) => {
          create.mutate(v);
        }}
      >
        <Form.Item name="name" label={t.clients.name} rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="inn" label={t.clients.inn}>
          <Input />
        </Form.Item>
        <Form.Item name="segment" label={t.clients.segment}>
          <Input />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/** Клиенты (SPEC §10.1): список, поиск, создание. */
export function ClientsPage() {
  const [search, setSearch] = useSearchParams();
  const q = search.get("q") ?? "";
  const query = useClients(q);
  const team = useTeam();
  const perms = usePermissionsQuery();
  const [open, setOpen] = useState(false);
  const create = allowed(perms.data, "clients", "write") ? (
    <Button
      type="primary"
      onClick={() => {
        setOpen(true);
      }}
    >
      {t.clients.create}
    </Button>
  ) : null;

  return (
    <PageBody>
      <PageHeader title={t.page.clients} extra={create} />
      <Input.Search
        allowClear
        defaultValue={q}
        aria-label={t.clients.search}
        placeholder={t.clients.search}
        className="filter-lg"
        onSearch={(v) => {
          setSearch(v ? { q: v } : {}, { replace: true });
        }}
      />
      <PageState query={query} inline>
        <Table<ClientListItem>
          rowKey="id"
          loading={query.isLoading}
          dataSource={query.data ?? []}
          scroll={{ x: 900 }}
          rowClassName={(c) => (c.is_active ? "" : "row-muted")}
          columns={columns(team.data ?? [])}
        />
      </PageState>
      <CreateClientDialog
        open={open}
        onClose={() => {
          setOpen(false);
        }}
      />
    </PageBody>
  );
}
