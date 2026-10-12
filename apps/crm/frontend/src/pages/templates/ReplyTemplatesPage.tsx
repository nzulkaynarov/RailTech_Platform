import { App as AntApp, Button, Form, Input, Modal, Space, Table, Typography } from "antd";
import { useState } from "react";

import type { ReplyTemplateIn, ReplyTemplateOut } from "../../api/generated/model";
import { useReplyTemplateMutations, useReplyTemplates } from "../../api/templateQueries";
import { EmptyState } from "../../components/EmptyState";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useConfirmDanger } from "../../hooks/useConfirmDanger";
import { t } from "../../i18n/ru";
import { formatWhen } from "../../lib/time";
import "../admin.css";

const tt = t.templates;
type Editing = { id: number | null; initial: ReplyTemplateIn } | null;
const BLANK: ReplyTemplateIn = { title: "", text: { ru: "", uz: "", en: "" } };

function TemplateDialog({
  editing,
  saving,
  onClose,
  onSave,
}: {
  editing: Editing;
  saving: boolean;
  onClose: () => void;
  onSave: (body: ReplyTemplateIn) => void;
}) {
  const [form] = Form.useForm<ReplyTemplateIn>();
  const required = [{ required: true, whitespace: true, message: tt.required }];
  return (
    <Modal
      open={editing !== null}
      title={editing?.id === null ? tt.dialogNew : tt.dialogEdit}
      okText={tt.save}
      cancelText={tt.cancel}
      okButtonProps={{ loading: saving }}
      onCancel={onClose}
      onOk={() => {
        form.submit();
      }}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        preserve={false}
        initialValues={editing?.initial ?? BLANK}
        onFinish={onSave}
      >
        <Form.Item name="title" label={tt.title} extra={tt.titleHint} rules={required}>
          <Input maxLength={120} />
        </Form.Item>
        <Form.Item name={["text", "ru"]} label={tt.textRu} rules={required}>
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} maxLength={4000} />
        </Form.Item>
        <Form.Item name={["text", "uz"]} label={tt.textUz} extra={tt.textHint}>
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} maxLength={4000} />
        </Form.Item>
        <Form.Item name={["text", "en"]} label={tt.textEn} extra={tt.textHint}>
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} maxLength={4000} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/** «Шаблоны ответов» (admin): готовые ответы для карточки лида (аудит 2026-10-12 §5). */
export function ReplyTemplatesPage() {
  const list = useReplyTemplates();
  const { message } = AntApp.useApp();
  const confirm = useConfirmDanger();
  const mutations = useReplyTemplateMutations(useApiErrorToast());
  const [editing, setEditing] = useState<Editing>(null);
  const add = () => {
    setEditing({ id: null, initial: BLANK });
  };
  const columns = [
    { title: tt.title, dataIndex: "title", key: "title" },
    {
      title: tt.textRu,
      key: "ru",
      ellipsis: true,
      responsive: ["md" as const],
      render: (_: unknown, row: ReplyTemplateOut) => row.text.ru,
    },
    {
      title: tt.updated,
      key: "updated",
      responsive: ["lg" as const],
      render: (_: unknown, row: ReplyTemplateOut) => formatWhen(row.updated_at),
    },
    {
      title: tt.actions,
      key: "actions",
      render: (_: unknown, row: ReplyTemplateOut) => (
        <Space wrap>
          <Button
            size="small"
            aria-label={`${tt.edit}: ${row.title}`}
            onClick={() => {
              setEditing({ id: row.id, initial: { title: row.title, text: row.text } });
            }}
          >
            {tt.edit}
          </Button>
          <Button
            size="small"
            danger
            aria-label={`${tt.remove}: ${row.title}`}
            onClick={() => {
              confirm({
                title: tt.removeConfirm.replace("{title}", row.title),
                okText: tt.remove,
                onOk: () =>
                  mutations.remove.mutateAsync(row.id).then(() => message.success(tt.removed)),
              });
            }}
          >
            {tt.remove}
          </Button>
        </Space>
      ),
    },
  ];
  return (
    <PageBody>
      <PageHeader
        title={t.page.templates}
        extra={
          <Button type="primary" onClick={add}>
            {tt.add}
          </Button>
        }
      />
      <Typography.Paragraph type="secondary">{tt.intro}</Typography.Paragraph>
      <PageState query={list}>
        {list.data?.length ? (
          <Table rowKey="id" columns={columns} dataSource={list.data} pagination={false} />
        ) : (
          <EmptyState
            title={tt.empty}
            hint={tt.emptyHint}
            action={{ label: tt.add, onClick: add }}
          />
        )}
      </PageState>
      <TemplateDialog
        editing={editing}
        saving={mutations.save.isPending}
        onClose={() => {
          setEditing(null);
        }}
        onSave={(body) => {
          if (!editing) return;
          mutations.save.mutate(
            { id: editing.id, body },
            {
              onSuccess: () => {
                setEditing(null);
                void message.success(tt.saved);
              },
            },
          );
        }}
      />
    </PageBody>
  );
}
