import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Input, Segmented, Select, Spin } from "antd";
import { lazy, Suspense, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../../app/access";
import { useAuth } from "../../../../app/auth/useAuth";
import { ApiError } from "../../../../shared/api/errors";
import type { EdsTemplate, EdsTemplateIn } from "../../../../shared/api/generated/model";
import {
  createEdsTemplate,
  getDownloadEdsTemplatePreviewQueryKey,
  getDownloadEdsTemplatePreviewUrl,
  getListEdsTemplatesQueryKey,
  previewEdsTemplate,
  resetEdsTemplate,
  updateEdsTemplate,
  useGetEdsTemplatePreview,
  useListEdsTemplates,
} from "../../../../shared/api/generated/platform-bff";
import { BodyEditor } from "../../../../shared/ui/BodyEditor/BodyEditor";
import {
  type Body,
  type BodyLang,
  type BodyNode,
  emptyDoc,
  fromBody,
  isBlank,
  toBody,
} from "../../../../shared/ui/BodyEditor/bodyModel";
import type { DataColumn } from "../../../../shared/ui/DataTable/DataTable";
import { useRenderedPdf } from "../../../../shared/ui/DocumentViewer/useRenderedPdf";
import { StatusTag } from "../../../../shared/ui/StatusTag";
import { useEditParam } from "../../settings/useEditParam";
import { ConfirmModal, EditorPage, ListTable } from "../common";

const PdfViewer = lazy(() => import("../../../../shared/ui/PdfViewer"));

const LANGS: BodyLang[] = ["ru", "uz", "en"];
const POLL_MS = 1500;
const DEBOUNCE_MS = 1000;

/**
 * Письма и служебки на бланке (TPL-4, план 3.6): шаблон — варианты на русском, узбекском и английском; встроенный можно
 * вернуть по умолчанию; справа — настоящий PDF текущего варианта на бланке компании.
 */
export function LetterTemplates() {
  const { t } = useTranslation("company");
  const { me } = useAuth();
  const editable = canEdit(me, "eds.inbox.register") || canEdit(me, "admin");
  const query = useListEdsTemplates();
  const items = query.data?.items ?? [];
  const [editing, setEditing] = useEditParam(query.data?.items);

  const columns: DataColumn<EdsTemplate>[] = [
    {
      id: "name",
      header: t("letterTemplates.columns.name"),
      width: null,
      cellClassName: "pf-ell",
      cell: (row) => (
        <Button
          type="link"
          className="pf-co-link"
          aria-label={t("letterTemplates.open", { name: row.name })}
          onClick={() => {
            setEditing(row);
          }}
        >
          {row.name}
        </Button>
      ),
    },
    {
      id: "kind",
      header: t("letterTemplates.columns.kind"),
      width: 160,
      cell: (row) => t(`letterTemplates.kinds.${row.kind}`),
    },
    {
      id: "languages",
      header: t("letterTemplates.columns.languages"),
      width: 120,
      cell: (row) => row.languages.map((l) => l.toUpperCase()).join(" "),
    },
    {
      id: "label",
      header: t("letterTemplates.columns.label"),
      width: 180,
      cell: (row) => (
        <span className="pf-co-tags">
          {row.is_default ? (
            <StatusTag tone="blue">{t("letterTemplates.default")}</StatusTag>
          ) : null}
          {row.changed ? <StatusTag tone="gold">{t("letterTemplates.changed")}</StatusTag> : null}
        </span>
      ),
    },
  ];

  return (
    <div className="pf-fp-stack">
      {editing === null ? (
        <>
          {editable ? (
            <div>
              <Button
                onClick={() => {
                  setEditing("new");
                }}
              >
                {t("letterTemplates.create")}
              </Button>
            </div>
          ) : null}
          <ListTable
            tableId="admin.templates.letters"
            label={t("letterTemplates.caption")}
            columns={columns}
            data={items}
            rowKey={(row) => row.id}
            loading={query.isPending}
            empty={{ title: t("letterTemplates.emptyTitle"), text: t("letterTemplates.emptyText") }}
          />
        </>
      ) : null}
      {editing !== null ? (
        <TemplateEditor
          row={editing === "new" ? null : editing}
          readOnly={!editable}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}

function initialVariants(row: EdsTemplate | null): Record<BodyLang, BodyNode> {
  const out = {} as Record<BodyLang, BodyNode>;
  for (const lang of LANGS) {
    const body = row?.variants[lang] as Body | undefined;
    out[lang] = body ? fromBody(body) : emptyDoc();
  }
  return out;
}

function TemplateEditor({
  row,
  readOnly,
  onClose,
}: {
  row: EdsTemplate | null;
  readOnly: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const client = useQueryClient();
  const [name, setName] = useState(row?.name ?? "");
  const [kind, setKind] = useState<EdsTemplateIn["kind"]>(row?.kind ?? "letter");
  const [isDefault, setIsDefault] = useState(row?.is_default ?? false);
  const [variants, setVariants] = useState(() => initialVariants(row));
  const [lang, setLang] = useState<BodyLang>("ru");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [resetting, setResetting] = useState(false);
  // Редактор неуправляемый: после «Вернуть по умолчанию» пересоздаётся с исходными текстами
  const [version, setVersion] = useState(0);

  const filled = LANGS.filter((l) => !isBlank(variants[l]));
  const refresh = () => client.invalidateQueries({ queryKey: getListEdsTemplatesQueryKey() });

  const save = async () => {
    setSaving(true);
    setError(null);
    const data: EdsTemplateIn = {
      kind,
      name: name.trim(),
      is_default: isDefault,
      variants: Object.fromEntries(filled.map((l) => [l, toBody(variants[l], l)])),
    };
    try {
      if (row) await updateEdsTemplate(row.id, data);
      else await createEdsTemplate(data);
      void message.success(t("saved"));
      await refresh();
      onClose();
    } catch (failure) {
      setError(failure);
    } finally {
      setSaving(false);
    }
  };

  return (
    <EditorPage
      title={row ? row.name : t("letterTemplates.createTitle")}
      formId="letter-template-form"
      submitLabel={t("letterTemplates.save")}
      saving={saving}
      error={error}
      readOnly={readOnly}
      onCancel={onClose}
    >
      <form
        id="letter-template-form"
        className="pf-co-split"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <div className="pf-fp-stack">
          <label htmlFor="tpl-name">{t("letterTemplates.name")}</label>
          <Input
            id="tpl-name"
            required
            maxLength={120}
            value={name}
            disabled={readOnly}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
          {row ? null : (
            <>
              <label htmlFor="tpl-kind">{t("letterTemplates.columns.kind")}</label>
              <Select
                id="tpl-kind"
                value={kind}
                onChange={setKind}
                options={(["letter", "memo"] as const).map((value) => ({
                  value,
                  label: t(`letterTemplates.kinds.${value}`),
                }))}
              />
            </>
          )}
          <Checkbox
            checked={isDefault}
            disabled={readOnly || Boolean(row?.is_default)}
            onChange={(event) => {
              setIsDefault(event.target.checked);
            }}
          >
            {t("letterTemplates.makeDefault")}
          </Checkbox>
          <Segmented
            aria-label={t("letterTemplates.language")}
            value={lang}
            onChange={(value) => {
              setLang(value);
            }}
            options={LANGS.map((value) => ({
              value,
              label: filled.includes(value) ? value.toUpperCase() : `${value.toUpperCase()} —`,
            }))}
          />
          <BodyEditor
            key={`${lang}:${String(version)}`}
            id={`tpl-body-${lang}`}
            label={t("letterTemplates.body", { lang: lang.toUpperCase() })}
            value={variants[lang]}
            disabled={readOnly}
            onChange={(doc) => {
              setVariants((prev) => ({ ...prev, [lang]: doc }));
            }}
          />
          <p className="pf-co-hint">{t("letterTemplates.emptyLanguage")}</p>
          {row?.origin === "builtin" && !readOnly ? (
            <div>
              <Button
                onClick={() => {
                  setResetting(true);
                }}
              >
                {t("letterTemplates.reset")}
              </Button>
            </div>
          ) : null}
        </div>
        <div className="pf-co-panel">
          <h3 className="pf-co-title">{t("letterTemplates.preview")}</h3>
          {isBlank(variants[lang]) ? (
            <p className="pf-co-hint">{t("letterTemplates.previewEmpty")}</p>
          ) : (
            <TemplatePdf body={toBody(variants[lang], lang)} kind={kind} />
          )}
        </div>
      </form>
      {row ? (
        <ConfirmModal
          open={resetting}
          title={t("letterTemplates.resetTitle", { name: row.name })}
          okLabel={t("letterTemplates.reset")}
          danger
          loading={false}
          onCancel={() => {
            setResetting(false);
          }}
          onOk={() => {
            void resetEdsTemplate(row.id).then(async (next) => {
              setResetting(false);
              setVariants(initialVariants(next));
              setVersion((n) => n + 1);
              setName(next.name);
              void message.success(t("letterTemplates.resetDone"));
              await refresh();
            });
          }}
        >
          <p>{t("letterTemplates.resetWhat")}</p>
        </ConfirmModal>
      ) : null}
    </EditorPage>
  );
}

/** PDF варианта на бланке: запрос через секунду после паузы в наборе, опрос, пока строится; прежние страницы остаются. */
function TemplatePdf({ body, kind }: { body: Body; kind: EdsTemplateIn["kind"] }) {
  const { t } = useTranslation("company");
  const key = JSON.stringify(body);
  const [hash, setHash] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      previewEdsTemplate({ body: JSON.parse(key) as Body, kind })
        .then((answer) => {
          setFailed(null);
          setHash(answer.hash);
        })
        .catch((error: unknown) => {
          setFailed(error instanceof ApiError ? error.message : t("letterTemplates.previewFailed"));
        });
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [key, kind, t]);
  const status = useGetEdsTemplatePreview(hash ?? "", {
    query: {
      enabled: Boolean(hash),
      refetchInterval: (query) => (query.state.data?.status === "pending" ? POLL_MS : false),
    },
  });
  const ready = status.data?.status === "ready";
  const bytes = useRenderedPdf({
    id: hash,
    ready,
    queryKey: getDownloadEdsTemplatePreviewQueryKey(hash ?? ""),
    url: getDownloadEdsTemplatePreviewUrl(hash ?? ""),
  });
  if (failed) return <Alert type="warning" showIcon message={failed} />;
  if (status.data?.status === "failed") {
    return (
      <Alert
        type="warning"
        showIcon
        message={status.data.error ?? t("letterTemplates.previewFailed")}
      />
    );
  }
  if (!bytes.data) {
    return (
      <div role="status">
        <Spin size="small" /> {t("letterTemplates.previewPending")}
      </div>
    );
  }
  return (
    <Suspense fallback={<Spin size="small" />}>
      <PdfViewer data={bytes.data} name={t("letterTemplates.preview")} />
    </Suspense>
  );
}
