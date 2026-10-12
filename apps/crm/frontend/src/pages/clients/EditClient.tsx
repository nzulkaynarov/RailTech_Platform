import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, App as AntApp, Button, Form, Input, Modal, Select, Switch } from "antd";
import { useState } from "react";

import { adminKeys } from "../../api/adminQueries";
import { getListClientsQueryKey, updateClient } from "../../api/generated/crm";
import type { ClientDetail, ClientUpdate } from "../../api/generated/model";
import { useTeam } from "../../api/queries";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";

function useSaveClient(client: ClientDetail, onSaved: () => void) {
  const query = useQueryClient();
  const { message } = AntApp.useApp();
  return useMutation({
    mutationFn: async (values: ClientUpdate) =>
      await updateClient(client.id, {
        ...values,
        inn: values.inn?.trim() || null,
        segment: values.segment?.trim() || null,
        notes: values.notes?.trim() || null,
        owner_user_id: values.owner_user_id ?? null,
      }),
    onSuccess: (_, values) => {
      onSaved();
      void message.success(t.clients.saved.replace("{name}", values.name ?? client.name));
      void query.invalidateQueries({ queryKey: adminKeys.client(client.id) });
      void query.invalidateQueries({ queryKey: getListClientsQueryKey() });
    },
    onError: useApiErrorToast(),
  });
}

/** Карточка клиента: правка полей; пустое поле очищает значение (ИНН, сегмент, ответственный). */
export function EditClient({ client }: { client: ClientDetail }) {
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<ClientUpdate>();
  const active = Form.useWatch("is_active", form);
  const team = useTeam();
  const save = useSaveClient(client, () => {
    setOpen(false);
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
