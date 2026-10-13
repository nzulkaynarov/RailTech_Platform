import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Input, Modal, Select, Space } from "antd";
import { useState } from "react";
import { Link } from "react-router";

import { useClients } from "../api/adminQueries";
import { getGetLeadQueryKey, makeCustomer } from "../api/generated/crm";
import { useApiErrorToast } from "../hooks/useApiErrorToast";
import { t } from "../i18n/ru";

type Props = { leadId: number; open: boolean; onClose: () => void };

/**
 * «Сделать клиентом» (Фаза 6): лид после сделки → клиент, Telegram подтверждён менеджером.
 * Карточку лида не покидаем: уведомление со ссылкой «Открыть карточку клиента».
 */
export function MakeCustomer({ leadId, open, onClose }: Props) {
  const [clientId, setClientId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const clients = useClients("");
  const query = useQueryClient();
  const { notification } = AntApp.useApp();
  const mutation = useMutation({
    mutationFn: async () =>
      await makeCustomer(leadId, {
        client_id: clientId,
        new_client_name: clientId ? null : name,
      }),
    onSuccess: (created) => {
      onClose();
      void query.invalidateQueries({ queryKey: getGetLeadQueryKey(leadId) });
      notification.success({
        message: t.lead.clientCreated,
        description: <Link to={`/clients/${String(created.id)}`}>{t.lead.openClient}</Link>,
      });
    },
    onError: useApiErrorToast(),
  });
  return (
    <Modal
      open={open}
      title={t.clients.makeCustomer}
      okText={t.clients.makeCustomer}
      cancelText={t.actions.cancel}
      confirmLoading={mutation.isPending}
      okButtonProps={{ disabled: clientId === null && !name.trim() }}
      onOk={() => {
        mutation.mutate();
      }}
      onCancel={onClose}
    >
      <Space direction="vertical" style={{ width: "100%" }}>
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          aria-label={t.clients.existing}
          placeholder={t.clients.existing}
          style={{ width: "100%" }}
          value={clientId}
          onChange={(v?: number) => {
            setClientId(v ?? null);
          }}
          options={(clients.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
        />
        <Input
          aria-label={t.clients.newName}
          placeholder={t.clients.newName}
          disabled={clientId !== null}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
      </Space>
    </Modal>
  );
}
