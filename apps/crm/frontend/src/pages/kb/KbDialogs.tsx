import { App, Button, Collapse, Form, Input, Modal, Select, Space } from "antd";
import { useState } from "react";
import type { SelectProps, UploadFile } from "antd";

import { useProducts } from "../../api/adminQueries";
import { FileDragger } from "../../components/FileDragger";
import { t } from "../../i18n/ru";
import { languageOptions } from "../../domain/labels";
import {
  downloadText,
  KB_EXAMPLE_FILENAME,
  KB_EXAMPLE_MD,
  KB_FORMAT_MD,
  kbPromptText,
} from "./kbDocs";

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

/** Краткая спецификация рядом с загрузкой; полный текст — из сборки (docs/kb), без внешних ссылок. */
function FormatHelp() {
  const { message } = App.useApp();
  const [specOpen, setSpecOpen] = useState(false);
  const copyPrompt = () => {
    navigator.clipboard.writeText(kbPromptText()).then(
      () => void message.success(t.kb.promptCopied),
      () => void message.error(t.kb.promptCopyFailed),
    );
  };
  return (
    <>
      <Collapse
        size="small"
        style={{ marginBottom: 16 }}
        items={[
          {
            key: "format",
            label: t.kb.formatTitle,
            children: (
              <>
                <p>{t.kb.formatIntro}</p>
                <ul>
                  {t.kb.formatRules.map((rule) => (
                    <li key={rule}>{rule}</li>
                  ))}
                </ul>
                <Space wrap>
                  <Button
                    size="small"
                    onClick={() => {
                      setSpecOpen(true);
                    }}
                  >
                    {t.kb.formatSpec}
                  </Button>
                  <Button size="small" onClick={copyPrompt}>
                    {t.kb.formatPrompt}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      downloadText(KB_EXAMPLE_FILENAME, KB_EXAMPLE_MD);
                    }}
                  >
                    {t.kb.formatExample}
                  </Button>
                </Space>
              </>
            ),
          },
        ]}
      />
      <Modal
        open={specOpen}
        title={t.kb.formatSpecTitle}
        onCancel={() => {
          setSpecOpen(false);
        }}
        footer={
          <Button
            onClick={() => {
              setSpecOpen(false);
            }}
          >
            {t.kb.formatClose}
          </Button>
        }
        width={760}
      >
        <pre
          tabIndex={0}
          aria-label={t.kb.formatSpecTitle}
          style={{ whiteSpace: "pre-wrap", maxHeight: "60vh", overflow: "auto", margin: 0 }}
        >
          {KB_FORMAT_MD}
        </pre>
      </Modal>
    </>
  );
}

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
      <FormatHelp />
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ language: "ru" }}>
        <Form.Item
          name="file"
          label={t.kb.file}
          valuePropName="fileList"
          getValueFromEvent={(e: { fileList: UploadFile[] }) => e.fileList.slice(-1)}
          rules={[{ required: true }]}
        >
          <FileDragger accept=".md" />
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
