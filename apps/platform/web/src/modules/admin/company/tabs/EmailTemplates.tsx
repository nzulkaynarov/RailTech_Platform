import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Checkbox, Form, Input, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { EmailTemplate } from "../../../../shared/api/generated/model";
import {
  getListEmailTemplatesQueryKey,
  useCreateEmailTemplate,
  useDeleteEmailTemplate,
  useListEmailTemplates,
  usePreviewEmailTemplate,
  useUpdateEmailTemplate,
} from "../../../../shared/api/generated/platform-bff";
import { StatusTag } from "../../../../shared/ui/StatusTag";
import { ConfirmModal, FormModal, ListTable, PreviewFrame, QueryGate } from "../common";
import { changedFields, isEmptyObject } from "../diff";
import { errorFields } from "../errors";

interface Values {
  key: string;
  language: string;
  subject: string;
  text_body: string;
  html_body: string;
  available_variables: string;
  is_active: boolean;
}

const LANGUAGES = ["ru", "uz", "en"] as const;

/** Шаблоны писем платформы: активный шаблон заменяет файловый для всех получателей, поэтому правка — с образцом и «Что произойдёт». */
export function EmailTemplates() {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const query = useListEmailTemplates();
  const [editing, setEditing] = useState<EmailTemplate | "new" | null>(null);
  const [removing, setRemoving] = useState<EmailTemplate | null>(null);
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: getListEmailTemplatesQueryKey() });
  const remove = useDeleteEmailTemplate({
    mutation: {
      onSuccess: () => {
        void refresh();
        setRemoving(null);
        void message.success(t("templates.emails.deleted"));
      },
    },
  });
  const add = (
    <Button
      type="primary"
      onClick={() => {
        setEditing("new");
      }}
    >
      {t("templates.emails.add")}
    </Button>
  );

  return (
    <QueryGate query={query}>
      {({ items }) => (
        <>
          {items.length > 0 ? <div>{add}</div> : null}
          <ListTable<EmailTemplate>
            label={t("templates.parts.emails")}
            data={items}
            rowKey={(row) => row.id}
            empty={{
              title: t("templates.emails.empty.title"),
              text: t("templates.emails.empty.text"),
              action: add,
            }}
            columns={[
              {
                title: t("templates.emails.key"),
                dataIndex: "key",
                render: (v: string) => <b className="pf-co-mono">{v}</b>,
              },
              { title: t("templates.emails.language"), dataIndex: "language" },
              { title: t("templates.emails.subject"), dataIndex: "subject", responsive: ["md"] },
              {
                title: t("status"),
                dataIndex: "is_active",
                render: (value: boolean) => (
                  <StatusTag tone={value ? "green" : "default"}>
                    {t(value ? "templates.emails.replaces" : "templates.emails.fileUsed")}
                  </StatusTag>
                ),
              },
              {
                title: t("actions"),
                key: "actions",
                render: (_: unknown, row) => (
                  <span className="pf-co-actions">
                    <Button
                      type="link"
                      size="small"
                      aria-label={t("editNamed", { name: row.key })}
                      onClick={() => {
                        setEditing(row);
                      }}
                    >
                      {t("edit")}
                    </Button>
                    <Button
                      type="link"
                      size="small"
                      danger
                      aria-label={t("deleteNamed", { name: row.key })}
                      onClick={() => {
                        remove.reset();
                        setRemoving(row);
                      }}
                    >
                      {t("delete")}
                    </Button>
                  </span>
                ),
              },
            ]}
          />
          {editing !== null ? (
            <EmailEditor
              row={editing === "new" ? null : editing}
              onClose={() => {
                setEditing(null);
              }}
              onSaved={() => {
                void refresh();
                setEditing(null);
                void message.success(t("saved"));
              }}
            />
          ) : null}
          <ConfirmModal
            open={removing !== null}
            title={t("templates.emails.deleteTitle", { name: removing?.key ?? "" })}
            okLabel={t("delete")}
            danger
            loading={remove.isPending}
            error={remove.error}
            items={[
              t("templates.emails.consequence.delete"),
              t("templates.emails.consequence.file"),
            ]}
            onOk={() => {
              if (removing) remove.mutate({ id: removing.id });
            }}
            onCancel={() => {
              setRemoving(null);
            }}
          />
        </>
      )}
    </QueryGate>
  );
}

function EmailEditor({
  row,
  onClose,
  onSaved,
}: {
  row: EmailTemplate | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation("company");
  const formId = useId();
  const [form] = Form.useForm<Values>();
  const initial: Values = row
    ? {
        key: row.key,
        language: row.language,
        subject: row.subject,
        text_body: row.text_body,
        html_body: row.html_body,
        available_variables: row.available_variables,
        is_active: row.is_active,
      }
    : {
        key: "",
        language: "ru",
        subject: "",
        text_body: "",
        html_body: "",
        available_variables: "",
        is_active: true,
      };
  const create = useCreateEmailTemplate({ mutation: { onSuccess: onSaved } });
  const update = useUpdateEmailTemplate({ mutation: { onSuccess: onSaved } });
  const mutation = row ? update : create;
  const preview = usePreviewEmailTemplate();
  const active = Form.useWatch("is_active", form) as boolean | undefined;

  const submit = (values: Values) => {
    const onError = (error: unknown) => {
      form.setFields(
        errorFields(error)
          .filter((name) => name in initial)
          .map((name) => ({
            name: name as keyof Values,
            errors: [t("templates.emails.invalidField")],
          })),
      );
    };
    if (row) {
      const changed = changedFields(initial, values);
      if (isEmptyObject(changed)) {
        onClose();
        return;
      }
      update.mutate({ id: row.id, data: changed }, { onError });
    } else {
      create.mutate({ data: values }, { onError });
    }
  };

  return (
    <FormModal
      open
      width={1040}
      title={row ? t("templates.emails.editTitle") : t("templates.emails.addTitle")}
      formId={formId}
      submitLabel={t("save")}
      saving={mutation.isPending}
      error={
        mutation.error && errorFields(mutation.error).length === 0 ? mutation.error : undefined
      }
      onCancel={onClose}
    >
      <div className="pf-co-split">
        <Form<Values>
          id={formId}
          form={form}
          layout="vertical"
          initialValues={initial}
          onFinish={submit}
        >
          <div className="pf-co-grid">
            <Form.Item
              name="key"
              label={t("templates.emails.key")}
              rules={[{ required: true, whitespace: true, message: t("required") }]}
            >
              <Input
                maxLength={100}
                className="pf-co-mono"
                disabled={row !== null}
                autoComplete="off"
              />
            </Form.Item>
            <Form.Item name="language" label={t("templates.emails.language")}>
              <Select options={LANGUAGES.map((value) => ({ value, label: value }))} />
            </Form.Item>
          </div>
          <Form.Item
            name="subject"
            label={t("templates.emails.subject")}
            rules={[{ required: true, whitespace: true, message: t("required") }]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="text_body"
            label={t("templates.emails.textBody")}
            rules={[{ required: true, whitespace: true, message: t("required") }]}
          >
            <Input.TextArea rows={5} />
          </Form.Item>
          <Form.Item name="html_body" label={t("templates.emails.htmlBody")}>
            <Input.TextArea rows={5} className="pf-co-mono" spellCheck={false} />
          </Form.Item>
          <Form.Item
            name="available_variables"
            label={t("templates.emails.variables")}
            extra={t("templates.emails.variablesHint", { example: "{{number}}" })}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="is_active" valuePropName="checked" style={{ marginBottom: 8 }}>
            <Checkbox>{t("templates.emails.activeLabel")}</Checkbox>
          </Form.Item>
          {active === true ? (
            <p className="pf-co-hint" role="status">
              {t("templates.emails.activeWarning")}
            </p>
          ) : null}
        </Form>
        <div className="pf-co-panel">
          <h3 className="pf-co-title">{t("templates.emails.previewTitle")}</h3>
          {row ? (
            <>
              <div>
                <Button
                  loading={preview.isPending}
                  onClick={() => {
                    preview.mutate({ id: row.id });
                  }}
                >
                  {t("templates.emails.showPreview")}
                </Button>
              </div>
              {preview.isError ? (
                <p className="pf-co-hint" role="alert">
                  {t("errors.DEFAULT")}
                </p>
              ) : null}
              {preview.data ? (
                <>
                  <p style={{ margin: 0 }}>
                    <b>{t("templates.emails.subject")}:</b> {preview.data.subject}
                  </p>
                  <PreviewFrame
                    html={
                      preview.data.html_body ||
                      `<pre style="font-family:inherit">${escapeHtml(preview.data.text_body)}</pre>`
                    }
                    title={t("templates.emails.previewFrame")}
                  />
                </>
              ) : null}
              <p className="pf-co-hint">{t("templates.emails.previewHint")}</p>
            </>
          ) : (
            <p className="pf-co-hint">{t("templates.emails.previewAfterSave")}</p>
          )}
        </div>
      </div>
    </FormModal>
  );
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"]/g, (c) => `&#${String(c.charCodeAt(0))};`);
}
