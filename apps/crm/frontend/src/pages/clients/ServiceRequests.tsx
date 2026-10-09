import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Form, Input, List, Modal, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link } from "react-router";

import { adminKeys } from "../../api/adminQueries";
import { closeServiceRequest } from "../../api/generated/crm";
import type { ServiceRequestOut } from "../../api/generated/model";
import { type ApiError, unwrap } from "../../api/http";
import { errorText, t } from "../../i18n/ru";

type Props = { clientId: number; requests: ServiceRequestOut[]; canWrite: boolean };

/** Сервисные запросы клиента: закрытие только с ответом, который уйдёт клиенту в бот. */
export function ServiceRequests({ clientId, requests, canWrite }: Props) {
  const [closing, setClosing] = useState<ServiceRequestOut | null>(null);
  const [form] = Form.useForm<{ resolution: string }>();
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const close = useMutation({
    mutationFn: async (v: { id: number; resolution: string }) =>
      unwrap(await closeServiceRequest(v.id, { resolution: v.resolution })),
    onSuccess: () => {
      setClosing(null);
      form.resetFields();
      void message.success(t.common.saved);
      void client.invalidateQueries({ queryKey: adminKeys.client(clientId) });
    },
    onError: (e) => void message.error(errorText((e as ApiError).code, e.message)),
  });

  return (
    <>
      <List
        size="small"
        dataSource={requests}
        renderItem={(r) => (
          <List.Item
            actions={
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
                : []
            }
          >
            <Space direction="vertical" size={0}>
              <Space size={8} wrap>
                <Tag color={r.status === "open" ? "orange" : "default"}>
                  {t.clients.requestStatus[r.status] ?? r.status}
                </Tag>
                <Typography.Text>{r.summary}</Typography.Text>
              </Space>
              <Typography.Text type="secondary">
                {dayjs(r.created_at).format("DD.MM.YYYY HH:mm")}
                {r.lead_id ? (
                  <>
                    {" · "}
                    <Link to={`/leads/${String(r.lead_id)}`}>{t.clients.fromLead}</Link>
                  </>
                ) : null}
              </Typography.Text>
              {r.resolution ? <Typography.Text>↳ {r.resolution}</Typography.Text> : null}
            </Space>
          </List.Item>
        )}
      />
      <Modal
        open={closing !== null}
        title={t.clients.closeTitle}
        okText={t.clients.sendAndClose}
        cancelText={t.actions.cancel}
        confirmLoading={close.isPending}
        onCancel={() => {
          setClosing(null);
        }}
        onOk={() => {
          form.submit();
        }}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">{closing?.summary}</Typography.Paragraph>
        <Form
          form={form}
          layout="vertical"
          onFinish={(v) => {
            if (closing) close.mutate({ id: closing.id, resolution: v.resolution });
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
    </>
  );
}
