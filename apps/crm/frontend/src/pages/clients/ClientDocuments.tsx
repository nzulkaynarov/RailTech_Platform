import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  App as AntApp,
  Button,
  DatePicker,
  Drawer,
  Form,
  Input,
  List,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Upload,
} from "antd";
import type { UploadFile } from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { useState } from "react";

import { adminKeys, useClientDocuments, useDocumentAccess } from "../../api/adminQueries";
import { updateDocument, uploadDocument } from "../../api/generated/crm";
import type { DocumentOut, BodyUploadDocumentType } from "../../api/generated/model";
import { type ApiError, downloadFile, unwrap } from "../../api/http";
import { errorText, t } from "../../i18n/ru";

type UploadValues = {
  type: BodyUploadDocumentType;
  title: string;
  number?: string;
  doc_date?: Dayjs;
  visible: boolean;
  file: UploadFile[];
};

const TYPE_OPTIONS = Object.entries(t.clients.types).map(([value, label]) => ({ value, label }));

/** Документы клиента: загрузка, видимость клиенту, скачивание, журнал доступа. */
export function ClientDocuments({ clientId, canWrite }: { clientId: number; canWrite: boolean }) {
  const { data, isLoading } = useClientDocuments(clientId);
  const [uploading, setUploading] = useState(false);
  const [accessOf, setAccessOf] = useState<DocumentOut | null>(null);
  const access = useDocumentAccess(accessOf?.id ?? null);
  const [form] = Form.useForm<UploadValues>();
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const onError = (e: unknown) => {
    void message.error(errorText((e as ApiError).code, (e as Error).message));
  };
  const refresh = () => client.invalidateQueries({ queryKey: adminKeys.clientDocuments(clientId) });

  const upload = useMutation({
    mutationFn: async (v: UploadValues) => {
      const file = v.file[0]?.originFileObj;
      if (!file) throw new Error(t.kb.file);
      return unwrap(
        await uploadDocument({
          file,
          client_id: clientId,
          type: v.type,
          title: v.title,
          number: v.number ?? null,
          doc_date: v.doc_date ? v.doc_date.format("YYYY-MM-DD") : null,
          visible: v.visible,
        }),
      );
    },
    onSuccess: () => {
      setUploading(false);
      void refresh();
    },
    onError,
  });
  const toggle = useMutation({
    mutationFn: async (d: DocumentOut) =>
      unwrap(await updateDocument(d.id, { is_visible_to_client: !d.is_visible_to_client })),
    onSuccess: () => void refresh(),
    onError,
  });

  return (
    <>
      {canWrite ? (
        <Button
          className="filters"
          onClick={() => {
            setUploading(true);
          }}
        >
          {t.clients.upload}
        </Button>
      ) : null}
      <Table<DocumentOut>
        rowKey="id"
        size="small"
        loading={isLoading}
        dataSource={data ?? []}
        scroll={{ x: 760 }}
        pagination={false}
        columns={[
          { title: t.clients.type, render: (_, d) => t.clients.types[d.type] ?? d.type },
          { title: t.clients.title, dataIndex: "title" },
          {
            title: t.clients.number,
            dataIndex: "number",
            render: (v: string | null) => v ?? t.common.none,
          },
          {
            title: t.clients.date,
            dataIndex: "doc_date",
            render: (v: string | null) => (v ? dayjs(v).format("DD.MM.YYYY") : t.common.none),
          },
          {
            title: t.clients.visible,
            render: (_, d) => (
              <Switch
                size="small"
                disabled={!canWrite}
                checked={d.is_visible_to_client}
                onChange={() => {
                  toggle.mutate(d);
                }}
              />
            ),
          },
          {
            title: t.clients.extract,
            render: (_, d) => <Tag>{t.kb.statuses[d.extract_status] ?? d.extract_status}</Tag>,
          },
          {
            title: "",
            render: (_, d) => (
              <Space>
                <Button
                  size="small"
                  onClick={() => {
                    void downloadFile(
                      `/api/v1/documents/${String(d.id)}/download`,
                      d.filename,
                    ).catch(onError);
                  }}
                >
                  {t.clients.download}
                </Button>
                <Button
                  size="small"
                  onClick={() => {
                    setAccessOf(d);
                  }}
                >
                  {t.clients.access}
                </Button>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        open={uploading}
        title={t.clients.upload}
        confirmLoading={upload.isPending}
        destroyOnHidden
        onCancel={() => {
          setUploading(false);
        }}
        onOk={() => {
          form.submit();
        }}
        okText={t.common.save}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ type: "contract", visible: true }}
          onFinish={(v) => {
            upload.mutate(v);
          }}
        >
          <Form.Item
            name="file"
            label={t.kb.file}
            valuePropName="fileList"
            rules={[{ required: true }]}
            getValueFromEvent={(e: { fileList: UploadFile[] }) => e.fileList.slice(-1)}
          >
            <Upload beforeUpload={() => false} maxCount={1}>
              <a>{t.kb.file}</a>
            </Upload>
          </Form.Item>
          <Form.Item name="type" label={t.clients.type} rules={[{ required: true }]}>
            <Select options={TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="title" label={t.clients.title} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="number" label={t.clients.number}>
            <Input />
          </Form.Item>
          <Form.Item name="doc_date" label={t.clients.date}>
            <DatePicker format="DD.MM.YYYY" />
          </Form.Item>
          <Form.Item name="visible" label={t.clients.visible} valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
      <Drawer
        open={accessOf !== null}
        title={`${t.clients.access}: ${accessOf?.title ?? ""}`}
        onClose={() => {
          setAccessOf(null);
        }}
      >
        <List
          loading={access.isLoading}
          dataSource={access.data ?? []}
          renderItem={(a) => (
            <List.Item>
              {dayjs(a.created_at).format("DD.MM.YY HH:mm")} ·{" "}
              {t.clients.accessBy[a.accessed_by_type] ?? a.accessed_by_type}
              {a.tg_user_id ? ` · tg ${String(a.tg_user_id)}` : ""}
            </List.Item>
          )}
        />
      </Drawer>
    </>
  );
}
