import {
  DatePicker,
  Drawer,
  Form,
  Input,
  List,
  Modal,
  Select,
  Switch,
  Upload,
  Typography,
} from "antd";
import type { UploadFile } from "antd";
import type { Dayjs } from "dayjs";

import { useDocumentAccess } from "../../api/adminQueries";
import type { BodyUploadDocumentType, DocumentOut } from "../../api/generated/model";
import { PageState } from "../../components/PageState";
import { actorLabel } from "../../domain/labels";
import { t } from "../../i18n/ru";
import { DATE_FORMAT, formatDateTime } from "../../lib/time";

export type UploadValues = {
  type: BodyUploadDocumentType;
  title: string;
  number?: string;
  doc_date?: Dayjs;
  visible: boolean;
  file: UploadFile[];
};

const TYPE_OPTIONS = Object.entries(t.clients.types).map(([value, label]) => ({ value, label }));

type UploadProps = {
  open: boolean;
  saving: boolean;
  onCancel: () => void;
  onSubmit: (v: UploadValues) => void;
};

export function UploadDocumentDialog({ open, saving, onCancel, onSubmit }: UploadProps) {
  const [form] = Form.useForm<UploadValues>();
  return (
    <Modal
      open={open}
      title={t.clients.upload}
      confirmLoading={saving}
      destroyOnHidden
      onCancel={onCancel}
      onOk={() => {
        form.submit();
      }}
      okText={t.clients.upload}
      cancelText={t.actions.cancel}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ type: "contract", visible: true }}
        onFinish={onSubmit}
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
          <DatePicker format={DATE_FORMAT} />
        </Form.Item>
        <Form.Item name="visible" label={t.clients.visible} valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/** Журнал доступа к документу: кто и когда открывал (бот — с Telegram ID). */
export function AccessDrawer({ doc, onClose }: { doc: DocumentOut | null; onClose: () => void }) {
  const access = useDocumentAccess(doc?.id ?? null);
  return (
    <Drawer
      open={doc !== null}
      title={`${t.clients.access}: ${doc?.title ?? ""}`}
      onClose={onClose}
    >
      {doc ? (
        <PageState query={access} variant="section">
          <List
            dataSource={access.data ?? []}
            locale={{
              emptyText: (
                <Typography.Text type="secondary">{t.clients.accessEmpty}</Typography.Text>
              ),
            }}
            renderItem={(a) => (
              <List.Item>
                {formatDateTime(a.created_at)} · {actorLabel(a.accessed_by_type)}
                {a.tg_user_id ? ` · ${t.clients.accessTg} ${String(a.tg_user_id)}` : ""}
              </List.Item>
            )}
          />
        </PageState>
      ) : null}
    </Drawer>
  );
}
