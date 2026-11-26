import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Checkbox, ConfigProvider, Form, Input, Select } from "antd";
import { RowActions, ROW_ACTIONS_WIDTH } from "../../../../shared/ui/RowActions";
import { useId, useState } from "react";
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
  useUpdateDocumentTemplate,
} from "../../../../shared/api/generated/platform-bff";
import { StatusTag } from "../../../../shared/ui/StatusTag";
import { ConfirmModal, EditorPage, FormModal, ListTable, QueryGate } from "../common";
import { SamplePdf } from "../SamplePdf";
import { LanguageTabs, TemplateWordButtons, useTemplateWord } from "../TemplateWord";
import { type DocumentTemplateLanguage, templateFileName } from "../templateWord";
import { useReadOnly } from "../useReadOnly";
import { changedFields, isEmptyObject, omit } from "../diff";
import { errorFields } from "../errors";
import { useEditParam } from "../../settings/useEditParam";

interface Values {
  name: string;
  kind: DocumentTemplateKind;
  body_html: string;
  is_active: boolean;
}

/** ДОК-13: «Письмо», «Рапорт» и «Произвольный» не предлагаются — письма пишутся на бланке в документообороте. */
const KINDS: DocumentTemplateKind[] = ["contract", "invoice", "act", "receipt", "delivery_note"];

/** Шаблоны документов компании: свои и образцы платформы («скопировать к себе»), редактор с подстановками и образцом. */
export function DocumentTemplates() {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const query = useListDocumentTemplates();
  const [copying, setCopying] = useState<DocumentTemplate | null>(null);
  const [removing, setRemoving] = useState<DocumentTemplate | null>(null);
  const [editing, setEditing] = useEditParam(query.data?.items);
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
          {editing === null ? (
            <>
              {items.length > 0 ? <div>{add}</div> : null}
              <ListTable<DocumentTemplate>
                tableId="admin.company.documentTemplates"
                label={t("templates.parts.documents")}
                data={items}
                rowKey={(row) => row.id}
                empty={{
                  title: t("templates.documents.empty.title"),
                  text: t("templates.documents.empty.text"),
                  action: add,
                }}
                columns={[
                  {
                    id: "name",
                    header: t("templates.documents.name"),
                    width: null,
                    cell: (row) => (
                      <Button
                        type="link"
                        className="pf-co-link"
                        aria-label={t(
                          row.is_sample && !readOnly
                            ? "templates.documents.previewNamed"
                            : "templates.documents.openNamed",
                          { name: row.name },
                        )}
                        onClick={() => {
                          setEditing(row);
                        }}
                      >
                        {row.name}
                      </Button>
                    ),
                  },
                  {
                    id: "kind_name",
                    header: t("templates.documents.kind"),
                    width: null,
                    cell: (row) => row.kind_name,
                  },
                  {
                    id: "status",
                    header: t("status"),
                    width: null,
                    cell: (row) => (
                      <span className="pf-co-actions">
                        <StatusTag kind="origin" status={row.is_sample ? "sample" : "own"}>
                          {t(
                            row.is_sample
                              ? "templates.documents.sample"
                              : "templates.documents.own",
                          )}
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
                    id: "actions",
                    header: t("actions"),
                    headerHidden: true,
                    width: ROW_ACTIONS_WIDTH,
                    cell: (row) =>
                      readOnly ? null : (
                        <RowActions
                          name={row.name}
                          items={
                            row.is_sample
                              ? [
                                  {
                                    key: "copy",
                                    label: t("templates.documents.copy"),
                                    onClick: () => {
                                      setCopying(row);
                                    },
                                  },
                                ]
                              : [
                                  {
                                    key: "edit",
                                    label: t("edit"),
                                    onClick: () => {
                                      setEditing(row);
                                    },
                                  },
                                  {
                                    key: "delete",
                                    label: t("delete"),
                                    danger: true,
                                    onClick: () => {
                                      remove.reset();
                                      setRemoving(row);
                                    },
                                  },
                                ]
                          }
                        />
                      ),
                  },
                ]}
              />
            </>
          ) : null}
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
  // Новый шаблон не пустой: сразу текст образца платформы вида «Договор» (у юридических видов есть обязательные блоки).
  const starter = samples.find((item) => item.kind === "contract")?.body_html ?? "";
  const [prefilled, setPrefilled] = useState<string | null>(row || !starter ? null : starter);
  const initial: Values = row
    ? { name: row.name, kind: row.kind, body_html: row.body_html, is_active: row.is_active }
    : { name: "", kind: "contract", body_html: starter, is_active: true };
  const create = useCreateDocumentTemplate({ mutation: { onSuccess: onSaved } });
  const update = useUpdateDocumentTemplate({ mutation: { onSuccess: onSaved } });
  const mutation = row ? update : create;
  const placeholders = useGetDocumentPlaceholders();
  const body = Form.useWatch("body_html", form) as string | undefined;
  // ШАБЛ-1: текст правят в Word; разметка спрятана, пока не попросят. Язык — вкладки RU / UZ / EN для файла и образца.
  const [language, setLanguage] = useState<DocumentTemplateLanguage>("ru");
  const [showMarkup, setShowMarkup] = useState(false);
  const [bodies, setBodies] = useState({
    uz: row?.body_html_uz ?? "",
    en: row?.body_html_en ?? "",
  });
  const word = useTemplateWord(language, (next) => {
    setBodies({ uz: next.body_html_uz, en: next.body_html_en });
    form.setFieldValue("body_html", next.body_html);
  });
  const kind = (Form.useWatch("kind", form) as DocumentTemplateKind | undefined) ?? initial.kind;

  // Образец — настоящий PDF генератора на бланке, ничего не сохраняется (ДОК-14).
  const own = body ?? initial.body_html;
  const text = language === "ru" ? own : bodies[language] || own;
  const filled = ["ru", ...(bodies.uz.trim() ? ["uz"] : []), ...(bodies.en.trim() ? ["en"] : [])];
  // Подстановки, которых нет в каталоге: ERP называет их, когда образец готов (C2A-G-5).
  const [unknown, setUnknown] = useState<string[]>([]);

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
    <EditorPage
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
          {/* Скачать можно и образец платформы, и без права на правки: форма отключена, эти кнопки — нет */}
          <ConfigProvider componentDisabled={false}>
            <div className="pf-co-word">
              <span className="pf-co-word-title">{t("templates.documents.bodyTitle")}</span>
              {row ? (
                <>
                  <LanguageTabs value={language} onChange={setLanguage} filled={filled} />
                  <TemplateWordButtons
                    template={row}
                    word={word}
                    canUpload={!readOnly && !row.is_locked}
                    canPdf={false}
                  />
                  <p className="pf-co-hint">
                    {row.is_locked
                      ? t("templates.word.lockedHint")
                      : language !== "ru" && !filled.includes(language)
                        ? t("templates.word.noTextHint")
                        : t("templates.word.howTo")}
                  </p>
                </>
              ) : (
                <p className="pf-co-hint">{t("templates.word.saveFirst")}</p>
              )}
              <Button
                type="link"
                className="pf-co-link"
                aria-expanded={showMarkup}
                onClick={() => {
                  setShowMarkup((value) => !value);
                }}
              >
                {showMarkup
                  ? t("templates.documents.hideMarkup")
                  : t("templates.documents.showMarkup")}
              </Button>
            </div>
          </ConfigProvider>
          {/* Поле остаётся в форме и скрытым: значение уходит при сохранении, даже если разметку не открывали */}
          <div hidden={!showMarkup}>
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
          </div>
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
          <SamplePdf
            request={{
              template_kind: kind,
              body_html: text,
              ...(row && !row.is_sample ? { template_id: Number(row.id) } : {}),
            }}
            title={t("templates.documents.previewFrame")}
            onWarnings={setUnknown}
            language={language}
            onLanguageChange={setLanguage}
            {...(row
              ? { downloadName: templateFileName(row.name, row.edition, language, "pdf") }
              : {})}
          />
          {unknown.map((code) => (
            <p key={code} className="pf-co-hint" role="status">
              {t("templates.documents.unknownWarning", { token: `{{${code}}}` })}
            </p>
          ))}
        </div>
      </div>
      {word.node}
    </EditorPage>
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
