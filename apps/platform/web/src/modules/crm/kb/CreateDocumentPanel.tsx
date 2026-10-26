import { App, Button, Collapse, Input, Modal, Select } from "antd";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import type { Language } from "../../../shared/api/generated/model";
import {
  useCreateManualKbDocument,
  useUploadKbDocument,
} from "../../../shared/api/generated/platform-bff";
import { Consequence } from "../../../shared/ui/Consequence";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { kbErrorText } from "./errors";
import {
  KB_EXAMPLE_FILENAME,
  KB_EXAMPLE_MD,
  KB_FORMAT_MD,
  downloadText,
  kbPromptText,
} from "./kbDocs";
import { ProductField } from "./ProductField";
import { MAX_UPLOAD_BYTES, productKeyValid, useRefreshKb, withParams } from "./refresh";

const LANGUAGES: readonly Language[] = ["ru", "uz", "en"];

export interface DocumentDraft {
  title: string;
  language: Language;
  markdown: string;
  gapId: number | null;
}

/** Краткая спецификация рядом с загрузкой; полный текст — из сборки (docs/kb), без внешних ссылок. */
function FormatHelp() {
  const { t } = useTranslation("kb");
  const { message } = App.useApp();
  const [specOpen, setSpecOpen] = useState(false);
  const copyPrompt = () => {
    navigator.clipboard.writeText(kbPromptText()).then(
      () => {
        void message.success(t("format.promptCopied"));
      },
      () => {
        void message.error(t("format.promptCopyFailed"));
      },
    );
  };
  return (
    <>
      <Collapse
        size="small"
        items={[
          {
            key: "format",
            label: t("format.title"),
            children: (
              <div className="pf-fp-form">
                <p className="pf-fp-sub">{t("format.intro")}</p>
                <ul className="pf-kb-rules">
                  {(t("format.rules", { returnObjects: true }) as string[]).map((rule) => (
                    <li key={rule}>{rule}</li>
                  ))}
                </ul>
                <div className="pf-fp-row">
                  <Button
                    size="small"
                    onClick={() => {
                      setSpecOpen(true);
                    }}
                  >
                    {t("format.spec")}
                  </Button>
                  <Button size="small" onClick={copyPrompt}>
                    {t("format.prompt")}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      downloadText(KB_EXAMPLE_FILENAME, KB_EXAMPLE_MD);
                    }}
                  >
                    {t("format.example")}
                  </Button>
                </div>
              </div>
            ),
          },
        ]}
      />
      <Modal
        open={specOpen}
        title={t("format.specTitle")}
        width={760}
        onCancel={() => {
          setSpecOpen(false);
        }}
        footer={
          <Button
            onClick={() => {
              setSpecOpen(false);
            }}
          >
            {t("format.close")}
          </Button>
        }
      >
        <pre tabIndex={0} aria-label={t("format.specTitle")} className="pf-kb-spec">
          {KB_FORMAT_MD}
        </pre>
      </Modal>
    </>
  );
}

function useCreated() {
  const { t } = useTranslation("kb");
  const { message } = App.useApp();
  const refresh = useRefreshKb();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  return (id: number, gapId: number | null) => {
    refresh();
    void message.success(t(gapId === null ? "create.done" : "create.doneGap"));
    // Документ открывается в боковом окне; из пробела — с переходом на вкладку «Документы».
    const changes: Record<string, string | null> = {
      doc: String(id),
      new: null,
      gap: null,
      panel: "open",
      ...(gapId === null ? {} : { view: "docs", status: null, page: null }),
    };
    void navigate({ search: withParams(params, changes) });
  };
}

function UploadForm({ gapId }: { gapId: number | null }) {
  const { t, i18n } = useTranslation("kb");
  const created = useCreated();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState<Language>("ru");
  const [product, setProduct] = useState("");
  const upload = useUploadKbDocument({
    mutation: {
      onSuccess: (out) => {
        created(out.id, gapId);
      },
    },
  });
  const checkFile = (next: File | null) => {
    setFile(next);
    if (next === null) setFileError(null);
    else if (!next.name.toLowerCase().endsWith(".md")) setFileError(t("create.errors.notMarkdown"));
    else if (next.size === 0) setFileError(t("create.errors.empty"));
    else if (next.size > MAX_UPLOAD_BYTES) setFileError(t("create.errors.tooLarge"));
    else setFileError(null);
  };
  const invalid =
    file === null ||
    fileError !== null ||
    title.trim() === "" ||
    !productKeyValid(product) ||
    upload.isPending;
  return (
    <form
      className="pf-fp-form"
      aria-label={t("create.upload.title")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (invalid) return;
        upload.mutate({
          data: {
            file,
            title: title.trim(),
            language,
            ...(product === "" ? {} : { product_key: product }),
            ...(gapId === null ? {} : { gap_id: gapId }),
          },
        });
      }}
    >
      <FormatHelp />
      <FormField
        id="kb-upload-file"
        label={t("create.upload.file")}
        hint={t("create.upload.fileHint")}
      >
        <input
          id="kb-upload-file"
          ref={fileInput}
          type="file"
          accept=".md,text/markdown"
          aria-invalid={fileError !== null || undefined}
          aria-describedby="kb-upload-file-hint"
          onChange={(event) => {
            const next = event.target.files?.[0] ?? null;
            checkFile(next);
            if (next && title.trim() === "") setTitle(next.name.replace(/\.md$/i, ""));
          }}
        />
      </FormField>
      <ErrorNote message={fileError} />
      <FormField id="kb-upload-title" label={t("fields.title")}>
        <Input
          id="kb-upload-title"
          value={title}
          maxLength={500}
          autoComplete="off"
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
      </FormField>
      <FormField id="kb-upload-language" label={t("fields.language")}>
        <Select
          id="kb-upload-language"
          value={language}
          options={LANGUAGES.map((value) => ({ value, label: t(`languages.${value}`) }))}
          onChange={setLanguage}
        />
      </FormField>
      <ProductField id="kb-upload-product" value={product} onChange={setProduct} />
      <Consequence
        items={[
          t(gapId === null ? "create.step1" : "create.step1Gap"),
          t("create.step2"),
          t("create.step3"),
        ]}
      />
      <ErrorNote message={upload.isError ? kbErrorText(t, upload.error, i18n.language) : null} />
      <div className="pf-fp-row">
        <Button type="primary" htmlType="submit" loading={upload.isPending} disabled={invalid}>
          {t("create.upload.submit")}
        </Button>
      </div>
    </form>
  );
}

export function ManualForm({ draft }: { draft: DocumentDraft | null }) {
  const { t, i18n } = useTranslation("kb");
  const created = useCreated();
  const gapId = draft?.gapId ?? null;
  const [title, setTitle] = useState(draft?.title ?? "");
  const [language, setLanguage] = useState<Language>(draft?.language ?? "ru");
  const [product, setProduct] = useState("");
  const [markdown, setMarkdown] = useState(draft?.markdown ?? "");
  const create = useCreateManualKbDocument({
    mutation: {
      onSuccess: (out) => {
        created(out.id, gapId);
      },
    },
  });
  const invalid =
    title.trim() === "" || markdown.trim() === "" || !productKeyValid(product) || create.isPending;
  return (
    <form
      className="pf-fp-form"
      aria-label={t("create.manual.title")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (invalid) return;
        create.mutate({
          data: {
            title: title.trim(),
            markdown,
            language,
            product_key: product === "" ? null : product,
            gap_id: gapId,
          },
        });
      }}
    >
      <FormField id="kb-manual-title" label={t("fields.title")}>
        <Input
          id="kb-manual-title"
          value={title}
          maxLength={500}
          autoComplete="off"
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
      </FormField>
      <FormField id="kb-manual-language" label={t("fields.language")}>
        <Select
          id="kb-manual-language"
          value={language}
          options={LANGUAGES.map((value) => ({ value, label: t(`languages.${value}`) }))}
          onChange={setLanguage}
        />
      </FormField>
      <ProductField id="kb-manual-product" value={product} onChange={setProduct} />
      <FormField id="kb-manual-text" label={t("fields.text")} hint={t("create.manual.textHint")}>
        <Input.TextArea
          id="kb-manual-text"
          rows={10}
          maxLength={200000}
          value={markdown}
          onChange={(event) => {
            setMarkdown(event.target.value);
          }}
        />
      </FormField>
      <Consequence
        items={[
          t(gapId === null ? "create.step1" : "create.step1Gap"),
          t("create.step2"),
          t("create.step3"),
        ]}
      />
      <ErrorNote message={create.isError ? kbErrorText(t, create.error, i18n.language) : null} />
      <div className="pf-fp-row">
        <Button type="primary" htmlType="submit" loading={create.isPending} disabled={invalid}>
          {t("create.manual.submit")}
        </Button>
      </div>
    </form>
  );
}

/** Новый документ в боковом окне: загрузка файла `.md` или ручной ввод; из пробела — с заготовкой и закрытием пробела. */
export function CreateDocumentPanel({
  kind,
  draft,
}: {
  kind: "upload" | "manual";
  draft: DocumentDraft | null;
}) {
  const { t } = useTranslation("kb");
  return (
    <div className="pf-fp-stack">
      <h3 className="pf-fp-title">
        {t(kind === "upload" ? "create.upload.title" : "create.manual.title")}
      </h3>
      {kind === "upload" ? (
        <UploadForm gapId={draft?.gapId ?? null} />
      ) : (
        <ManualForm draft={draft} />
      )}
    </div>
  );
}
