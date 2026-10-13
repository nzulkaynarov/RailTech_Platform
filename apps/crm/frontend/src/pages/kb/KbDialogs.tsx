import { Form, Input, Modal, Select } from "antd";
import type { SelectProps, UploadFile } from "antd";

import { useProducts } from "../../api/adminQueries";
import { FileDragger } from "../../components/FileDragger";
import { t } from "../../i18n/ru";
import { languageOptions } from "../../domain/labels";

export type UploadValues = {
  title: string;
  language: "ru" | "uz" | "en";
  product_key?: string;
  file: UploadFile[];
};
export type ManualValues = {
  title: string;
  language: "ru" | "uz" | "en";
  product_key?: string;
  markdown: string;
};

const LANGUAGES = languageOptions();

/** `id`, `value` и `onChange` приходят от `Form.Item`: без `id` подпись поля не связана со списком. */
function ProductSelect(props: SelectProps<string>) {
  const { data } = useProducts();
  return (
    <Select
      {...props}
      allowClear
      options={(data ?? []).map((p) => ({ value: p.key, label: `${p.name} (${p.key})` }))}
    />
  );
}

type DialogProps<T> = {
  open: boolean;
  saving: boolean;
  initial?: Partial<T>;
  onCancel: () => void;
  onSubmit: (values: T) => void;
};

export function UploadDialog({ open, saving, onCancel, onSubmit }: DialogProps<UploadValues>) {
  const [form] = Form.useForm<UploadValues>();
  return (
    <Modal
      open={open}
      title={t.kb.upload}
      confirmLoading={saving}
      onCancel={onCancel}
      onOk={() => {
        form.submit();
      }}
      destroyOnHidden
      okText={t.common.save}
    >
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ language: "ru" }}>
        <Form.Item
          name="file"
          label={t.kb.file}
          valuePropName="fileList"
          getValueFromEvent={(e: { fileList: UploadFile[] }) => e.fileList.slice(-1)}
          rules={[{ required: true }]}
        >
          <FileDragger accept=".pdf,.docx,.pptx,.xlsx,.md,.html,.htm,.txt" />
        </Form.Item>
        <Form.Item name="title" label={t.kb.title} rules={[{ required: true, max: 500 }]}>
          <Input />
        </Form.Item>
        <Form.Item name="language" label={t.kb.language} rules={[{ required: true }]}>
          <Select options={LANGUAGES} />
        </Form.Item>
        <Form.Item name="product_key" label={t.kb.product}>
          <ProductSelect />
        </Form.Item>
      </Form>
    </Modal>
  );
}

export function ManualDialog({
  open,
  saving,
  initial,
  onCancel,
  onSubmit,
}: DialogProps<ManualValues>) {
  const [form] = Form.useForm<ManualValues>();
  return (
    <Modal
      open={open}
      title={t.kb.manual}
      confirmLoading={saving}
      onCancel={onCancel}
      onOk={() => {
        form.submit();
      }}
      destroyOnHidden
      okText={t.common.save}
      width={720}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={onSubmit}
        initialValues={{ language: "ru", ...initial }}
      >
        <Form.Item name="title" label={t.kb.title} rules={[{ required: true, max: 500 }]}>
          <Input />
        </Form.Item>
        <Form.Item name="language" label={t.kb.language} rules={[{ required: true }]}>
          <Select options={LANGUAGES} />
        </Form.Item>
        <Form.Item name="product_key" label={t.kb.product}>
          <ProductSelect />
        </Form.Item>
        <Form.Item name="markdown" label={t.kb.text} rules={[{ required: true }]}>
          <Input.TextArea rows={12} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
