import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Checkbox, Form, Input, Select } from "antd";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  DocumentTemplate,
  DocumentTemplateKind,
} from "../../../../shared/api/generated/model";
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
import { changedFields, isEmptyObject, omit } from "../diff";
import { errorFields } from "../errors";

interface Values {
  name: string;
  kind: DocumentTemplateKind;
  body_html: string;
  is_active: boolean;
}

const KINDS: DocumentTemplateKind[] = [
  "letter",
  "report",
  "custom",
  "contract",
  "invoice",
  "act",
  "receipt",
  "delivery_note",
];

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
                    <StatusTag kind="origin" status={row.is_sample ? "sample" : "own"}>
                      {t(row.is_sample ? "templates.documents.sample" : "templates.documents.own")}
                    </StatusTag>
                    {!row.is_active ? (
                      <StatusTag kind="activity" status="inactive">
                        {t("inactive")}
                      </StatusTag>
                    ) : null}
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
                    <span className="pf-co-actions">
                      <Button
                        type="primary"
                        size="small"
                        aria-label={t("templates.documents.previewNamed", { name: row.name })}
                        onClick={() => {
                          setEditing(row);
                        }}
                      >
                        {t("templates.documents.preview")}
                      </Button>
                      <Button
                        size="small"
                        aria-label={t("templates.documents.copyNamed", { name: row.name })}
                        onClick={() => {
                          setCopying(row);
                        }}
                      >
                        {t("templates.documents.copy")}
                      </Button>
                    </span>
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
              samples={items.filter((item) => item.is_sample)}
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
  samples,
  onClose,
  onSaved,
  readOnly: noRight,
}: {
  row: DocumentTemplate | null;
  samples: readonly DocumentTemplate[];
  onClose: () => void;
  onSaved: () => void;
  readOnly: boolean;
}) {
  const { t } = useTranslation("company");
  const formId = useId();
  const [form] = Form.useForm<Values>();
  // Образец платформы открывается только на просмотр (правит копия), как и всё — без права «полный» на раздел.
  const readOnly = noRight || (row?.is_sample ?? false);
  const [prefilled, setPrefilled] = useState<string | null>(null);
  const initial: Values = row
    ? { name: row.name, kind: row.kind, body_html: row.body_html, is_active: row.is_active }
    : { name: "", kind: "custom", body_html: "", is_active: true };
  const create = useCreateDocumentTemplate({ mutation: { onSuccess: onSaved } });
  const update = useUpdateDocumentTemplate({ mutation: { onSuccess: onSaved } });
  const mutation = row ? update : create;
  const placeholders = useGetDocumentPlaceholders();
  const body = Form.useWatch("body_html", form) as string | undefined;
  const kind = (Form.useWatch("kind", form) as DocumentTemplateKind | undefined) ?? initial.kind;

  // Образец на тестовых данных ERP: после паузы ввода, ничего не сохраняется.
  const preview = usePreviewDocumentTemplate();
  const { mutate: requestPreview } = preview;
  const text = body ?? initial.body_html;
  // Подстановки, которых нет в каталоге: ERP называет их в предупреждениях образца (C2A-G-5).
  const unknown = preview.data?.warnings ?? [];
  useEffect(() => {
    const timer = window.setTimeout(() => {
      requestPreview({ data: { body_html: text, kind } });
    }, 400);
    return () => {
      window.clearTimeout(timer);
    };
  }, [text, kind, requestPreview]);

  // Новый шаблон договора, счёта или акта не пустой: подставляется образец платформы этого вида, если текст ещё не трогали.
  const chooseKind = (next: DocumentTemplateKind) => {
    if (row) return;
    const current = (form.getFieldValue("body_html") as string | undefined) ?? "";
    if (current.trim() !== "" && current !== prefilled) return;
    const sample = samples.find((item) => item.kind === next);
    form.setFieldValue("body_html", sample ? sample.body_html : "");
    setPrefilled(sample ? sample.body_html : null);
  };

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
      // Вид после создания не меняется (поля в форме нет): сравниваем и отправляем без него.
      const changed = changedFields(omit(initial, ["kind"]), omit(values, ["kind"]));
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
          ? row?.is_sample
            ? t("templates.documents.viewSampleTitle")
            : t("templates.documents.viewTitle")
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
          {row?.is_sample ? (
            <p className="pf-co-hint">{t("templates.documents.viewSampleHint")}</p>
          ) : null}
          {row ? (
            // Вид задаётся при создании: у готового шаблона он показан словом, без отключённого поля (контраст).
            <Form.Item
              label={t("templates.documents.kindField")}
              extra={t("templates.documents.kindFixed")}
            >
              <span>{t(`templates.documents.kinds.${row.kind}`)}</span>
            </Form.Item>
          ) : (
            <Form.Item
              name="kind"
              label={t("templates.documents.kindField")}
              extra={t("templates.documents.kindHint")}
            >
              <Select<DocumentTemplateKind>
                onChange={chooseKind}
                options={KINDS.map((value) => ({
                  value,
                  label: t(`templates.documents.kinds.${value}`),
                }))}
              />
            </Form.Item>
          )}
          <Form.Item
            name="body_html"
            label={t("templates.documents.body")}
            extra={
              prefilled !== null && prefilled === body
                ? t("templates.documents.prefilled")
                : t("templates.documents.bodyHint", { example: "{{counterparty.name}}" })
            }
          >
            <Input.TextArea rows={12} className="pf-co-mono" spellCheck={false} />
          </Form.Item>
          <Form.Item name="is_active" valuePropName="checked" style={{ marginBottom: 12 }}>
            <Checkbox>{t("templates.documents.activeLabel")}</Checkbox>
          </Form.Item>
          <details className="pf-co-details" open={unknown.length > 0 ? true : undefined}>
            <summary>
              {t("templates.documents.placeholders")}
              {unknown.length > 0
                ? ` · ${t("templates.documents.placeholdersUnknown", { count: unknown.length })}`
                : ""}
            </summary>
            {unknown.length > 0 ? (
              <div>
                <p className="pf-co-hint">
                  <b>{t("templates.documents.unknownTitle")}</b>
                </p>
                <ul className="pf-co-tree pf-co-tree-root">
                  {unknown.map((code) => (
                    <li key={code}>
                      <code className="pf-co-mono">{`{{${code}}}`}</code> —{" "}
                      {t("templates.documents.unknownMark")}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
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
          {unknown.map((code) => (
            <p key={code} className="pf-co-hint" role="status">
              {t("templates.documents.unknownWarning", { token: `{{${code}}}` })}
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
