import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Checkbox, Form, Input } from "antd";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { DocumentTemplate } from "../../../../shared/api/generated/model";
import {
  getListDocumentTemplatesQueryKey,
  useCopyDocumentTemplate,
  useCreateDocumentTemplate,
  useDeleteDocumentTemplate,
  useGetDocumentPlaceholders,
  useListDocumentTemplates,
  usePreviewDocumentTemplate,
  useUpdateDocumentTemplate,
} from "../../../../shared/api/generated/platform-bff";
import { StatusTag } from "../../../../shared/ui/StatusTag";
import { ConfirmModal, FormModal, ListTable, PreviewFrame, QueryGate } from "../common";
import { useReadOnly } from "../useReadOnly";
import { changedFields, isEmptyObject } from "../diff";
import { errorFields } from "../errors";

interface Values {
  name: string;
  body_html: string;
  is_active: boolean;
}

/** Шаблоны документов компании: свои и образцы платформы («скопировать к себе»), редактор с подстановками и образцом. */
export function DocumentTemplates() {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const query = useListDocumentTemplates();
  const [editing, setEditing] = useState<DocumentTemplate | "new" | null>(null);
  const [copying, setCopying] = useState<DocumentTemplate | null>(null);
  const [removing, setRemoving] = useState<DocumentTemplate | null>(null);
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: getListDocumentTemplatesQueryKey() });
  const remove = useDeleteDocumentTemplate({
    mutation: {
      onSuccess: () => {
        void refresh();
        setRemoving(null);
        void message.success(t("templates.documents.deleted"));
      },
    },
  });
  const readOnly = useReadOnly();
  const add = (
    <Button
      type="primary"
      disabled={readOnly}
      onClick={() => {
        setEditing("new");
      }}
    >
      {t("templates.documents.add")}
    </Button>
  );

  return (
    <QueryGate query={query}>
      {({ items }) => (
        <>
          {items.length > 0 ? <div>{add}</div> : null}
          <ListTable<DocumentTemplate>
            label={t("templates.parts.documents")}
            data={items}
            rowKey={(row) => row.id}
            empty={{
              title: t("templates.documents.empty.title"),
              text: t("templates.documents.empty.text"),
              action: add,
            }}
            columns={[
              { title: t("templates.documents.name"), dataIndex: "name" },
              {
                title: t("templates.documents.kind"),
                dataIndex: "kind_name",
                responsive: ["md"],
              },
              {
                title: t("status"),
                key: "status",
                render: (_: unknown, row) => (
                  <span className="pf-co-actions">
                    <StatusTag tone={row.is_sample ? "blue" : "default"}>
                      {t(row.is_sample ? "templates.documents.sample" : "templates.documents.own")}
                    </StatusTag>
                    {!row.is_active ? <StatusTag tone="default">{t("inactive")}</StatusTag> : null}
                  </span>
                ),
              },
              {
                title: t("actions"),
                key: "actions",
                render: (_: unknown, row) =>
                  readOnly ? (
                    <Button
                      type="link"
                      size="small"
                      aria-label={t("templates.documents.openNamed", { name: row.name })}
                      onClick={() => {
                        setEditing(row);
                      }}
                    >
                      {t("templates.documents.open")}
                    </Button>
                  ) : row.is_sample ? (
                    <Button
                      type="link"
                      size="small"
                      aria-label={t("templates.documents.copyNamed", { name: row.name })}
                      onClick={() => {
                        setCopying(row);
                      }}
                    >
                      {t("templates.documents.copy")}
                    </Button>
                  ) : (
                    <span className="pf-co-actions">
                      <Button
                        type="link"
                        size="small"
                        aria-label={t("editNamed", { name: row.name })}
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
                        aria-label={t("deleteNamed", { name: row.name })}
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
            <DocumentEditor
              row={editing === "new" ? null : editing}
              readOnly={readOnly}
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
          {copying !== null ? (
            <CopyModal
              row={copying}
              onClose={() => {
                setCopying(null);
              }}
              onCopied={() => {
                void refresh();
                setCopying(null);
                void message.success(t("templates.documents.copied"));
              }}
            />
          ) : null}
          <ConfirmModal
            open={removing !== null}
            title={t("templates.documents.deleteTitle", { name: removing?.name ?? "" })}
            okLabel={t("delete")}
            danger
            loading={remove.isPending}
            error={remove.error}
            items={[
              t("templates.documents.consequence.delete"),
              t("templates.documents.consequence.inUse"),
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

function DocumentEditor({
  row,
  onClose,
  onSaved,
  readOnly,
}: {
  row: DocumentTemplate | null;
  onClose: () => void;
  onSaved: () => void;
  readOnly: boolean;
}) {
  const { t } = useTranslation("company");
  const formId = useId();
  const [form] = Form.useForm<Values>();
  const initial: Values = row
    ? { name: row.name, body_html: row.body_html, is_active: row.is_active }
    : { name: "", body_html: "", is_active: true };
  const create = useCreateDocumentTemplate({ mutation: { onSuccess: onSaved } });
  const update = useUpdateDocumentTemplate({ mutation: { onSuccess: onSaved } });
  const mutation = row ? update : create;
  const placeholders = useGetDocumentPlaceholders();
  const body = Form.useWatch("body_html", form) as string | undefined;

  // Образец на тестовых данных ERP: после паузы ввода, ничего не сохраняется.
  const preview = usePreviewDocumentTemplate();
  const { mutate: requestPreview } = preview;
  const text = body ?? initial.body_html;
  useEffect(() => {
    const timer = window.setTimeout(() => {
      requestPreview({ data: { body_html: text } });
    }, 400);
    return () => {
      window.clearTimeout(timer);
    };
  }, [text, requestPreview]);

  const submit = (values: Values) => {
    const onError = (error: unknown) => {
      form.setFields(
        errorFields(error)
          .filter((name) => name in initial)
          .map((name) => ({
            name: name as keyof Values,
            errors: [t("templates.documents.invalidField")],
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
      title={
        readOnly
          ? t("templates.documents.viewTitle")
          : row
            ? t("templates.documents.editTitle")
            : t("templates.documents.addTitle")
      }
      formId={formId}
      submitLabel={t("save")}
      saving={mutation.isPending}
      error={
        mutation.error && errorFields(mutation.error).length === 0 ? mutation.error : undefined
      }
      onCancel={onClose}
      readOnly={readOnly}
    >
      <div className="pf-co-split">
        <Form<Values>
          disabled={readOnly}
          id={formId}
          form={form}
          layout="vertical"
          initialValues={initial}
          onFinish={submit}
        >
          <Form.Item
            name="name"
            label={t("templates.documents.name")}
            rules={[{ required: true, whitespace: true, message: t("required") }]}
          >
            <Input maxLength={255} autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="body_html"
            label={t("templates.documents.body")}
            extra={t("templates.documents.bodyHint", { example: "{{buyer_name}}" })}
          >
            <Input.TextArea rows={12} className="pf-co-mono" spellCheck={false} />
          </Form.Item>
          <Form.Item name="is_active" valuePropName="checked" style={{ marginBottom: 12 }}>
            <Checkbox>{t("templates.documents.activeLabel")}</Checkbox>
          </Form.Item>
          <details className="pf-co-details">
            <summary>{t("templates.documents.placeholders")}</summary>
            {(placeholders.data?.groups ?? []).map((group) => (
              <div key={group.key}>
                <p className="pf-co-hint">
                  <b>{group.label}</b>
                </p>
                <ul className="pf-co-tree pf-co-tree-root">
                  {group.items.map((item) => (
                    <li key={item.code}>
                      <code className="pf-co-mono">{`{{${item.code}}}`}</code> — {item.label}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </details>
        </Form>
        <div className="pf-co-panel">
          <h3 className="pf-co-title">{t("templates.documents.previewTitle")}</h3>
          <PreviewFrame
            html={preview.data?.html}
            title={t("templates.documents.previewFrame")}
            loading={preview.isPending}
          />
          {(preview.data?.warnings ?? []).map((warning) => (
            <p key={warning} className="pf-co-hint" role="status">
              {warning}
            </p>
          ))}
        </div>
      </div>
    </FormModal>
  );
}

function CopyModal({
  row,
  onClose,
  onCopied,
}: {
  row: DocumentTemplate;
  onClose: () => void;
  onCopied: () => void;
}) {
  const { t } = useTranslation("company");
  const formId = useId();
  const copy = useCopyDocumentTemplate({ mutation: { onSuccess: onCopied } });
  return (
    <FormModal
      open
      title={t("templates.documents.copyTitle", { name: row.name })}
      formId={formId}
      submitLabel={t("templates.documents.copy")}
      saving={copy.isPending}
      error={copy.error}
      onCancel={onClose}
    >
      <Form<{ name: string }>
        id={formId}
        layout="vertical"
        initialValues={{ name: t("templates.documents.copyName", { name: row.name }) }}
        onFinish={(values) => {
          copy.mutate({ id: row.id, data: { name: values.name.trim() } });
        }}
      >
        <Form.Item
          name="name"
          label={t("templates.documents.name")}
          rules={[{ required: true, whitespace: true, message: t("required") }]}
        >
          <Input maxLength={255} autoComplete="off" />
        </Form.Item>
        <p className="pf-co-hint" style={{ margin: 0 }}>
          {t("templates.documents.copyHint")}
        </p>
      </Form>
    </FormModal>
  );
}
