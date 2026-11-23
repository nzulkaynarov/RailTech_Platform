import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Input, Radio, Skeleton } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { LegalContent } from "../../../shared/api/generated/model";
import {
  getGetLegalEditionQueryKey,
  getListLegalEditionsQueryKey,
  useGetLegalEdition,
  useUpdateLegalEdition,
} from "../../../shared/api/generated/platform-bff";
import { ContextualSaveBar } from "../../../shared/ui/ContextualSaveBar";
import { Dialog } from "../../../shared/ui/Dialog";
import { legalErrorText } from "./errors";
import type { LegalLang } from "./LegalText";

import "./legal.css";

const LANGS: readonly LegalLang[] = ["ru", "uz", "en"];
const PLACEHOLDERS =
  "{{company.name}}, {{company.inn}}, {{company.address}}, {{company.support_email}}, {{company.phone}}";

const blank = { ru: "", uz: "", en: "" };

/**
 * Правка черновика: название редакции, язык текста (три языка — одна структура разделов) и сами тексты полями — название,
 * вводный абзац, разделы. Добавление и удаление раздела действует на все языки сразу. Сохраняется черновик; опубликовать
 * его можно из списка редакций, поэтому правка клиентов не затрагивает.
 */
export function LegalEditor({ id, onClose }: { id: string; onClose: (saved?: boolean) => void }) {
  const { t } = useTranslation("legal");
  const query = useGetLegalEdition(id);
  if (query.isPending) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (query.isError) {
    return (
      <Alert
        type="error"
        showIcon
        role="alert"
        message={t("loadError")}
        action={
          <Button
            onClick={() => {
              void query.refetch();
            }}
          >
            {t("retry")}
          </Button>
        }
      />
    );
  }
  return (
    <Form
      key={query.data.id}
      id={id}
      kind={query.data.kind}
      initialLabel={query.data.label}
      initialContent={query.data.content}
      onClose={onClose}
    />
  );
}

function Form({
  id,
  kind,
  initialLabel,
  initialContent,
  onClose,
}: {
  id: string;
  kind: "privacy" | "terms";
  initialLabel: string;
  initialContent: LegalContent;
  onClose: (saved?: boolean) => void;
}) {
  const { t, i18n } = useTranslation("legal");
  const ids = useId();
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState({ label: initialLabel, content: initialContent });
  const [label, setLabel] = useState(initialLabel);
  const [content, setContent] = useState<LegalContent>(initialContent);
  const [lang, setLang] = useState<LegalLang>(
    (LANGS as readonly string[]).includes(i18n.language) ? (i18n.language as LegalLang) : "ru",
  );
  const [leaving, setLeaving] = useState(false);
  const update = useUpdateLegalEdition();

  const dirty = label !== saved.label || JSON.stringify(content) !== JSON.stringify(saved.content);

  const setSection = (index: number, field: "title" | "body", value: string) => {
    setContent((prev) => ({
      ...prev,
      sections: prev.sections.map((section, i) =>
        i === index ? { ...section, [field]: { ...section[field], [lang]: value } } : section,
      ),
    }));
  };
  const addSection = () => {
    setContent((prev) => ({
      ...prev,
      sections: [...prev.sections, { title: { ...blank }, body: { ...blank } }],
    }));
  };
  const removeSection = (index: number) => {
    setContent((prev) => ({ ...prev, sections: prev.sections.filter((_, i) => i !== index) }));
  };

  const save = () => {
    update.mutate(
      { id, data: { label: label.trim(), content } },
      {
        onSuccess: (edition) => {
          setSaved({ label: edition.label, content: edition.content });
          setLabel(edition.label);
          setContent(edition.content);
          queryClient.setQueryData(getGetLegalEditionQueryKey(id), edition);
          void queryClient.invalidateQueries({ queryKey: getListLegalEditionsQueryKey() });
          onClose(true);
        },
      },
    );
  };
  const close = () => {
    if (dirty) setLeaving(true);
    else onClose();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <Button onClick={close}>{t("actions.back")}</Button>
      </div>
      <h2 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
        {t("editor.title", { kind: t(`kinds.${kind}`) })}
      </h2>
      <form
        aria-label={t("editor.title", { kind: t(`kinds.${kind}`) })}
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (dirty) save();
        }}
      >
        {update.error ? (
          <Alert
            type="error"
            showIcon
            role="alert"
            message={legalErrorText(t, update.error)}
            style={{ marginBottom: 16 }}
          />
        ) : null}
        <div className="pf-legal-field" style={{ maxWidth: 360 }}>
          <label htmlFor={`${ids}-label`}>{t("editor.label")}</label>
          <Input
            id={`${ids}-label`}
            value={label}
            maxLength={40}
            aria-describedby={`${ids}-label-help`}
            onChange={(event) => {
              setLabel(event.target.value);
            }}
          />
          <div id={`${ids}-label-help`} className="pf-hint">
            {t("editor.labelHelp")}
          </div>
        </div>
        <Radio.Group
          aria-label={t("editor.language")}
          optionType="button"
          value={lang}
          options={LANGS.map((value) => ({ value, label: t(`languages.${value}`) }))}
          onChange={(event) => {
            setLang(event.target.value as LegalLang);
          }}
        />
        <p className="pf-hint" style={{ margin: "8px 0 16px" }}>
          {t("editor.threeLanguages")}
        </p>
        <div className="pf-legal-field">
          <label htmlFor={`${ids}-title-${lang}`}>{t("editor.docTitle")}</label>
          <Input
            id={`${ids}-title-${lang}`}
            lang={lang}
            value={content.title[lang]}
            onChange={(event) => {
              setContent((prev) => ({
                ...prev,
                title: { ...prev.title, [lang]: event.target.value },
              }));
            }}
          />
        </div>
        <div className="pf-legal-field">
          <label htmlFor={`${ids}-lead-${lang}`}>{t("editor.lead")}</label>
          <Input.TextArea
            id={`${ids}-lead-${lang}`}
            lang={lang}
            rows={3}
            value={content.lead[lang]}
            onChange={(event) => {
              setContent((prev) => ({
                ...prev,
                lead: { ...prev.lead, [lang]: event.target.value },
              }));
            }}
          />
          <div className="pf-hint">{t("editor.bodyHelp", { list: PLACEHOLDERS })}</div>
        </div>
        {content.sections.map((section, index) => (
          <fieldset key={index} className="pf-legal-section" style={{ border: 0, margin: 0 }}>
            <legend className="pf-legal-section-head" style={{ width: "100%", padding: 0 }}>
              <strong>{t("editor.section", { n: index + 1 })}</strong>
            </legend>
            <div className="pf-legal-field">
              <label htmlFor={`${ids}-s${String(index)}-title-${lang}`}>
                {t("editor.sectionTitle")}
              </label>
              <Input
                id={`${ids}-s${String(index)}-title-${lang}`}
                lang={lang}
                value={section.title[lang]}
                onChange={(event) => {
                  setSection(index, "title", event.target.value);
                }}
              />
            </div>
            <div className="pf-legal-field">
              <label htmlFor={`${ids}-s${String(index)}-body-${lang}`}>
                {t("editor.sectionBody")}
              </label>
              <Input.TextArea
                id={`${ids}-s${String(index)}-body-${lang}`}
                lang={lang}
                autoSize={{ minRows: 4, maxRows: 16 }}
                value={section.body[lang]}
                onChange={(event) => {
                  setSection(index, "body", event.target.value);
                }}
              />
            </div>
            <Button
              danger
              size="small"
              disabled={content.sections.length <= 1}
              onClick={() => {
                removeSection(index);
              }}
            >
              {t("editor.removeSection", { n: index + 1 })}
            </Button>
          </fieldset>
        ))}
        <Button onClick={addSection}>{t("editor.addSection")}</Button>
        <p className="pf-hint" style={{ margin: "16px 0 0" }}>
          {t("editor.consequence")}
        </p>
        <ContextualSaveBar
          visible={dirty}
          message={t("editor.unsaved")}
          saveLabel={t("editor.save")}
          loading={update.isPending}
          onSave={save}
          onDiscard={() => {
            setLabel(saved.label);
            setContent(saved.content);
            update.reset();
          }}
        />
      </form>
      <Dialog
        open={leaving}
        title={t("editor.discardTitle")}
        okLabel={t("editor.discardOk")}
        cancelLabel={t("editor.discardCancel")}
        danger
        onOk={() => {
          setLeaving(false);
          onClose();
        }}
        onCancel={() => {
          setLeaving(false);
        }}
      >
        {t("editor.discardText")}
      </Dialog>
    </div>
  );
}
