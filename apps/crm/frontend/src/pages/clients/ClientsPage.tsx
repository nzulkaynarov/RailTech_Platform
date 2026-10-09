import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Form, Input, Modal, Space, Table, Tag } from "antd";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useClients } from "../../api/adminQueries";
import { createClient } from "../../api/generated/crm";
import type { ClientCreate, ClientOut } from "../../api/generated/model";
import { type ApiError, unwrap } from "../../api/http";
import { usePermissionsQuery } from "../../api/queries";
import { allowed } from "../../app/providers/access";
import { errorText, t } from "../../i18n/ru";
import "../pages.css";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";

/** Клиенты (SPEC §10.1): список, поиск, создание. */
export function ClientsPage() {
  const [search, setSearch] = useSearchParams();
  const q = search.get("q") ?? "";
  const query = useClients(q);
  const { data, isLoading } = query;
  const perms = usePermissionsQuery();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<ClientCreate>();
  const navigate = useNavigate();
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const create = useMutation({
    mutationFn: async (values: ClientCreate) => unwrap(await createClient(values)),
    onSuccess: (created) => {
      setOpen(false);
      void client.invalidateQueries({ queryKey: ["clients"] });
      void navigate(`/clients/${String(created.id)}`);
    },
    onError: (e) => {
      void message.error(errorText((e as ApiError).code, e.message));
    },
  });

  return (
    <>
      <PageHeader
        title={t.page.clients}
        extra={
          allowed(perms.data, "clients", "write") ? (
            <Button
              type="primary"
              onClick={() => {
                setOpen(true);
              }}
            >
              {t.clients.create}
            </Button>
          ) : null
        }
      />
      <Space wrap className="filters">
        <Input.Search
          allowClear
          defaultValue={q}
          placeholder={t.clients.search}
          style={{ width: 260 }}
          onSearch={(v) => {
            setSearch(v ? { q: v } : {}, { replace: true });
          }}
        />
      </Space>
      <PageState query={query} inline>
        <Table<ClientOut>
          rowKey="id"
          loading={isLoading}
          dataSource={data ?? []}
          scroll={{ x: 560 }}
          columns={[
            {
              title: t.clients.name,
              render: (_, c) => <Link to={`/clients/${String(c.id)}`}>{c.name}</Link>,
            },
            {
              title: t.clients.inn,
              dataIndex: "inn",
              render: (v: string | null) => v ?? t.common.none,
            },
            {
              title: t.clients.segment,
              dataIndex: "segment",
              render: (v: string | null) => v ?? t.common.none,
            },
            {
              title: t.clients.active,
              render: (_, c) =>
                c.is_active ? <Tag color="green">{t.common.yes}</Tag> : <Tag>{t.common.no}</Tag>,
            },
          ]}
        />
      </PageState>
      <Modal
        open={open}
        title={t.clients.create}
        confirmLoading={create.isPending}
        destroyOnHidden
        onCancel={() => {
          setOpen(false);
        }}
        onOk={() => {
          form.submit();
        }}
        okText={t.common.save}
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
    </>
  );
}
