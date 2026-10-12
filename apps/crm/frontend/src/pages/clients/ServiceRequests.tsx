import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Form, Input, List, Modal, Space, Typography } from "antd";
import { useState } from "react";

import { adminKeys } from "../../api/adminQueries";
import { closeServiceRequest } from "../../api/generated/crm";
import type { ServiceRequestOut } from "../../api/generated/model";
import { LeadLink } from "../../components/EntityLink";
import { EmptyState } from "../../components/EmptyState";
import { RequestStatusTag } from "../../components/StageBadge";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { t } from "../../i18n/ru";
import { formatDateTime } from "../../lib/time";

type Props = { clientId: number; requests: ServiceRequestOut[]; canWrite: boolean };
type CloseProps = { clientId: number; request: ServiceRequestOut | null; onClose: () => void };

/** Закрытие запроса — только с ответом, который уйдёт клиенту в бот. */
function CloseRequestDialog({ clientId, request, onClose }: CloseProps) {
  const [form] = Form.useForm<{ resolution: string }>();
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const close = useMutation({
    mutationFn: async (v: { id: number; resolution: string }) =>
      await closeServiceRequest(v.id, { resolution: v.resolution }),
    onSuccess: () => {
      onClose();
      void message.success(t.clients.closed);
      void client.invalidateQueries({ queryKey: adminKeys.client(clientId) });
    },
    onError: useApiErrorToast(),
  });
  return (
    <Modal
      open={request !== null}
      title={t.clients.closeTitle}
      okText={t.clients.sendAndClose}
      cancelText={t.actions.cancel}
      confirmLoading={close.isPending}
      onCancel={onClose}
      onOk={() => {
        form.submit();
      }}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">{request?.summary}</Typography.Paragraph>
      <Form
        form={form}
        layout="vertical"
        onFinish={(v) => {
          if (request) close.mutate({ id: request.id, resolution: v.resolution });
        }}
      >
        <Form.Item
          name="resolution"
          label={t.clients.resolution}
          extra={t.clients.resolutionHint}
          rules={[{ required: true, whitespace: true, max: 2000 }]}
        >
          <Input.TextArea rows={3} autoFocus />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function RequestText({ r }: { r: ServiceRequestOut }) {
  return (
    <Space direction="vertical" size={0}>
      <Space size={8} wrap>
        <RequestStatusTag status={r.status} />
        <Typography.Text>{r.summary}</Typography.Text>
      </Space>
      <Typography.Text type="secondary">
        {formatDateTime(r.created_at)}
        {r.lead_id ? (
          <>
            {" · "}
            <LeadLink id={r.lead_id}>{t.clients.fromLead}</LeadLink>
          </>
        ) : null}
      </Typography.Text>
      {r.resolution ? <Typography.Text>↳ {r.resolution}</Typography.Text> : null}
    </Space>
  );
}

/** Сервисные запросы клиента; пусто — объяснение, откуда они берутся. */
export function ServiceRequests({ clientId, requests, canWrite }: Props) {
  const [closing, setClosing] = useState<ServiceRequestOut | null>(null);
  if (!requests.length) {
    return (
      <EmptyState compact title={t.clients.requestsEmpty} hint={t.clients.requestsEmptyHint} />
    );
  }
  const actions = (r: ServiceRequestOut) =>
    canWrite && r.status === "open"
      ? [
          <Button
            key="close"
            size="small"
            onClick={() => {
              setClosing(r);
            }}
          >
            {t.clients.close}
          </Button>,
        ]
      : [];
  return (
    <>
      <List
        size="small"
        dataSource={requests}
        renderItem={(r) => (
          <List.Item actions={actions(r)}>
            <RequestText r={r} />
          </List.Item>
        )}
      />
      <CloseRequestDialog
        clientId={clientId}
        request={closing}
        onClose={() => {
          setClosing(null);
        }}
      />
    </>
  );
}
