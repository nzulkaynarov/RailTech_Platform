import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Input, Modal, Select, Space } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router";

import { useClients } from "../api/adminQueries";
import { makeCustomer } from "../api/generated/crm";
import { type ApiError, unwrap } from "../api/http";
import { errorText, t } from "../i18n/ru";

/** «Сделать клиентом» (Фаза 6): лид после сделки → клиент, Telegram подтверждён менеджером. */
export function MakeCustomer({ leadId }: { leadId: number }) {
  const [open, setOpen] = useState(false);
  const [clientId, setClientId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const clients = useClients("");
  const query = useQueryClient();
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const mutation = useMutation({
    mutationFn: async () =>
      unwrap(
        await makeCustomer(leadId, {
          client_id: clientId,
          new_client_name: clientId ? null : name,
        }),
      ),
    onSuccess: (created) => {
      setOpen(false);
      void query.invalidateQueries({ queryKey: ["lead", leadId] });
      void navigate(`/clients/${String(created.id)}`);
    },
    onError: (e) => {
      void message.error(errorText((e as ApiError).code, e.message));
    },
  });
  return (
    <>
      <Button
        onClick={() => {
          setOpen(true);
        }}
      >
        {t.clients.makeCustomer}
      </Button>
      <Modal
        open={open}
        title={t.clients.makeCustomer}
        confirmLoading={mutation.isPending}
        okButtonProps={{ disabled: clientId === null && !name.trim() }}
        onOk={() => {
          mutation.mutate();
        }}
        onCancel={() => {
          setOpen(false);
        }}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder={t.clients.existing}
            style={{ width: "100%" }}
            value={clientId}
            onChange={(v?: number) => {
              setClientId(v ?? null);
            }}
            options={(clients.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
          />
          <Input
            placeholder={t.clients.newName}
            disabled={clientId !== null}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
        </Space>
      </Modal>
    </>
  );
}
