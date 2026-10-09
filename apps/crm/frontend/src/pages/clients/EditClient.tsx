import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, App as AntApp, Button, Form, Input, Modal, Select, Switch } from "antd";
import { useState } from "react";

import { adminKeys } from "../../api/adminQueries";
import { updateClient } from "../../api/generated/crm";
import type { ClientOut, ClientUpdate } from "../../api/generated/model";
import { type ApiError, unwrap } from "../../api/http";
import { useTeam } from "../../api/queries";
import { errorText, t } from "../../i18n/ru";

/** Карточка клиента: правка полей; пустое поле очищает значение (ИНН, сегмент, ответственный). */
export function EditClient({ client }: { client: ClientOut }) {
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<ClientUpdate>();
  const active = Form.useWatch("is_active", form);
  const team = useTeam();
  const query = useQueryClient();
  const { message } = AntApp.useApp();
  const save = useMutation({
    mutationFn: async (values: ClientUpdate) =>
      unwrap(
        await updateClient(client.id, {
          ...values,
          inn: values.inn?.trim() || null,
          segment: values.segment?.trim() || null,
          notes: values.notes?.trim() || null,
          owner_user_id: values.owner_user_id ?? null,
        }),
      ),
    onSuccess: () => {
      setOpen(false);
      void message.success(t.common.saved);
      void query.invalidateQueries({ queryKey: adminKeys.client(client.id) });
      void query.invalidateQueries({ queryKey: ["clients"] });
    },
    onError: (e) => {
      void message.error(errorText((e as ApiError).code, e.message));
    },
  });
  return (
    <>
      <Button
        onClick={() => {
          form.setFieldsValue(client);
          setOpen(true);
        }}
      >
        {t.clients.edit}
      </Button>
      <Modal
        open={open}
        title={t.clients.edit}
        okText={t.common.save}
        cancelText={t.actions.cancel}
        confirmLoading={save.isPending}
        onOk={() => {
          form.submit();
        }}
        onCancel={() => {
          setOpen(false);
        }}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => {
            save.mutate(values);
          }}
        >
          <Form.Item name="name" label={t.clients.name} rules={[{ required: true, max: 255 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="inn" label={t.clients.inn} rules={[{ max: 32 }]}>
            <Input allowClear />
          </Form.Item>
          <Form.Item name="segment" label={t.clients.segment} rules={[{ max: 64 }]}>
            <Input allowClear />
          </Form.Item>
          <Form.Item name="owner_user_id" label={t.clients.owner}>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={(team.data ?? []).map((m) => ({ value: m.id, label: m.full_name }))}
            />
          </Form.Item>
          <Form.Item name="notes" label={t.clients.notes} rules={[{ max: 4000 }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="is_active" label={t.clients.active} valuePropName="checked">
            <Switch />
          </Form.Item>
          {client.is_active && active === false ? (
            <Alert type="warning" showIcon message={t.clients.deactivateHint} />
          ) : null}
        </Form>
      </Modal>
    </>
  );
}
