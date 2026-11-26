import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Segmented } from "antd";
import { type ReactNode, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import { downloadFile } from "../../../shared/api/download";
import type {
  DocumentTemplate,
  TemplateWordCheck,
  WordChange,
} from "../../../shared/api/generated/model";
import {
  getDownloadTemplateWordUrl,
  getListContractTemplatesQueryKey,
  getListDocumentTemplatesQueryKey,
  useApplyTemplateWord,
  useCheckTemplateWord,
} from "../../../shared/api/generated/platform-bff";
import { FilePicker } from "../../../shared/ui/FileField";
import { FormSheet } from "../../../shared/ui/FormSheet";
import { companyErrorText } from "./errors";
import {
  type DocumentTemplateLanguage,
  WORD_LANGUAGES,
  downloadTemplatePdf,
  templateFileName,
} from "./templateWord";

/** Что нужно знать о шаблоне для файла: номер и название — в имени, `is_locked` — в подсказке. */
export interface WordTemplate {
  id: string;
  name: string;
  edition: number;
}

const DOCX = ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

/** Слова пункта с подсветкой: слева удалённое, справа добавленное, общее — как есть. */
function Segments({ item, side }: { item: WordChange; side: "ours" | "theirs" }) {
  if (item.segments.length === 0) return <>{side === "ours" ? item.ours : item.theirs}</>;
  const own = side === "ours" ? "del" : "ins";
  const other = side === "ours" ? "ins" : "del";
  return (
    <>
      {item.segments
        .filter((s) => s.op !== other)
        .map((s, i) =>
          s.op === own ? (
            side === "ours" ? (
              <del key={i}>{s.text}</del>
            ) : (
              <ins key={i}>{s.text}</ins>
            )
          ) : (
            <span key={i}>{s.text}</span>
          ),
        )}
    </>
  );
}

/** Отказ загрузки словами: причина ERP (`details.reason`) → текст про файл; иначе общий текст ошибки раздела. */
export function wordErrorText(
  t: (key: string, options?: { defaultValue: string }) => string,
  error: unknown,
) {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (typeof reason === "string") {
      const text = t(`company:templates.word.errors.${reason}`, { defaultValue: "" });
      if (text) return text;
    }
    if (error.status === 413) return t("company:templates.word.errors.word_too_big");
  }
  return companyErrorText(t as never, error);
}

function CheckSheet({
  check,
  language,
  applying,
  error,
  onAccept,
  onCancel,
}: {
  check: TemplateWordCheck;
  language: DocumentTemplateLanguage;
  applying: boolean;
  error: unknown;
  onAccept: (confirmLoss: boolean) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("company");
  const [understood, setUnderstood] = useState(false);
  const count = (kind: WordChange["kind"]) => check.items.filter((i) => i.kind === kind).length;
  const none = check.unchanged;
  const sameText = !none && !check.formatting_only && check.items.length === 0;
  const loses = check.lost_markup.length > 0;
  return (
    <FormSheet
      layer="drawer"
      wide
      title={t("templates.word.sheetTitle", { language: language.toUpperCase() })}
      submitLabel={t("templates.word.accept")}
      saving={applying}
      submitDisabled={!check.can_apply || (loses && !understood)}
      onSubmit={() => {
        onAccept(loses);
      }}
      onCancel={onCancel}
      error={
        error ? (
          <Alert type="error" showIcon role="alert" message={wordErrorText(t, error)} />
        ) : undefined
      }
    >
      <div className="pf-co-word">
        {none ? (
          <p className="pf-co-hint" role="status">
            {t("templates.word.nothingChanged")}
          </p>
        ) : sameText ? (
          <p role="status">{t("templates.word.sameTextDropped")}</p>
        ) : (
          <p role="status">
            {check.formatting_only
              ? t("templates.word.formattingOnly")
              : t("templates.word.summary", {
                  changed: count("changed"),
                  added: count("added"),
                  removed: count("removed"),
                })}
          </p>
        )}
        {check.locked ? (
          <Alert type="warning" showIcon message={t("templates.word.locked")} />
        ) : null}
        {check.missing_blocks.length > 0 ? (
          <Alert
            type="error"
            showIcon
            role="alert"
            message={t("templates.word.missingBlocks")}
            description={
              <ul className="pf-co-word-list">
                {check.missing_blocks.map((b) => (
                  <li key={b.code}>{b.label}</li>
                ))}
              </ul>
            }
          />
        ) : null}
        {check.unknown_placeholders.length > 0 ? (
          <Alert
            type="warning"
            showIcon
            message={t("templates.word.unknown", { count: check.unknown_placeholders.length })}
            description={
              <>
                <p className="pf-co-word-note">{t("templates.word.unknownHint")}</p>
                <ul className="pf-co-word-list">
                  {check.unknown_placeholders.map((code) => (
                    <li key={code}>
                      <code className="pf-co-mono">
                        {code.includes("{") ? code : `{{${code}}}`}
                      </code>
                    </li>
                  ))}
                </ul>
              </>
            }
          />
        ) : null}
        {check.dropped.length > 0 ? (
          <Alert
            type="info"
            showIcon
            message={t("templates.word.dropped")}
            description={
              <ul className="pf-co-word-list">
                {check.dropped.map((item) => (
                  <li key={item.kind}>
                    {t(`templates.word.droppedKind.${item.kind}`, {
                      count: item.count,
                      defaultValue: item.kind,
                    })}
                  </li>
                ))}
              </ul>
            }
          />
        ) : null}
        {loses ? (
          <Alert
            type="warning"
            showIcon
            message={t("templates.word.loses")}
            description={
              <>
                <ul className="pf-co-word-list">
                  {check.lost_markup.map((item) => (
                    <li key={item.kind}>
                      {t(`templates.word.lostKind.${item.kind}`, {
                        count: item.count,
                        defaultValue: item.kind,
                      })}
                    </li>
                  ))}
                </ul>
                <Checkbox
                  checked={understood}
                  onChange={(event) => {
                    setUnderstood(event.target.checked);
                  }}
                >
                  {t("templates.word.understood")}
                </Checkbox>
              </>
            }
          />
        ) : null}
        <ol className="pf-co-word-changes" aria-label={t("templates.word.changesLabel")}>
          {check.items.map((item, i) => (
            <li key={i} className={`pf-co-word-change pf-co-word-${item.kind}`}>
              <p className="pf-co-word-head">
                {item.point
                  ? t("templates.word.point", { point: item.point })
                  : t("templates.word.noPoint")}{" "}
                · {t(`templates.word.kind.${item.kind}`)}
              </p>
              <div className="pf-co-word-sides">
                <div>
                  <span className="pf-co-word-side">{t("templates.word.was")}</span>
                  <p>{item.kind === "added" ? "—" : <Segments item={item} side="ours" />}</p>
                </div>
                <div>
                  <span className="pf-co-word-side">{t("templates.word.becomes")}</span>
                  <p>{item.kind === "removed" ? "—" : <Segments item={item} side="theirs" />}</p>
                </div>
              </div>
            </li>
          ))}
        </ol>
        {check.summary.total > check.items.length ? (
          <p className="pf-co-hint">
            {t("templates.word.more", { count: check.summary.total - check.items.length })}
          </p>
        ) : null}
      </div>
    </FormSheet>
  );
}

/**
 * Шаблон в Word (ШАБЛ-1): «Скачать Word», «Скачать PDF», «Загрузить из Word». Один код для редактора шаблона документа и
 * для списка шаблонов договоров. Загрузка сначала проверяется (что изменилось, неизвестные подстановки), сохраняется только
 * после «Принять изменения».
 *
 * `upload(row)` открывает выбор файла; `node` — скрытое поле файла и боковая панель проверки, их выводит вызывающий один раз.
 */
export function useTemplateWord(
  language: DocumentTemplateLanguage,
  onApplied?: (next: DocumentTemplate) => void,
) {
  const { t } = useTranslation("company");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const opener = useRef<HTMLButtonElement>(null);
  const [target, setTarget] = useState<WordTemplate | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [check, setCheck] = useState<TemplateWordCheck | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const checking = useCheckTemplateWord();
  const applying = useApplyTemplateWord();

  const reset = () => {
    setFile(null);
    setCheck(null);
    applying.reset();
  };

  const download = async (row: WordTemplate) => {
    setBusy(`word:${row.id}`);
    try {
      await downloadFile(
        getDownloadTemplateWordUrl(row.id, { language }),
        templateFileName(row.name, row.edition, language, "docx"),
      );
    } catch (error) {
      void message.error(wordErrorText(t, error));
    } finally {
      setBusy(null);
    }
  };
  const downloadPdf = async (row: WordTemplate) => {
    setBusy(`pdf:${row.id}`);
    try {
      await downloadTemplatePdf(row, language);
    } catch (error) {
      void message.error(
        error instanceof ApiError ? wordErrorText(t, error) : t("templates.word.pdfFailed"),
      );
    } finally {
      setBusy(null);
    }
  };
  const upload = (row: WordTemplate) => {
    setTarget(row);
    reset();
    opener.current?.click();
  };
  const picked = (files: File[]) => {
    const chosen = files[0];
    if (!chosen || !target) return;
    setFile(chosen);
    checking.mutate(
      { id: target.id, data: { file: chosen }, params: { language } },
      {
        onSuccess: setCheck,
        onError: (error) => {
          setFile(null);
          void message.error(wordErrorText(t, error));
        },
      },
    );
  };
  const accept = (confirmLoss: boolean) => {
    if (!target || !file || !check) return;
    applying.mutate(
      {
        id: target.id,
        data: { file },
        params: {
          language,
          base: check.base,
          file_sha: check.file_sha,
          ...(confirmLoss ? { confirm_loss: true } : {}),
        },
      },
      {
        onSuccess: (next) => {
          void queryClient.invalidateQueries({ queryKey: getListDocumentTemplatesQueryKey() });
          void queryClient.invalidateQueries({ queryKey: getListContractTemplatesQueryKey() });
          reset();
          void message.success(t("templates.word.applied"));
          onApplied?.(next);
        },
      },
    );
  };

  const node: ReactNode = (
    <>
      {/* Системное поле файла запрещено: открывает его общий `FilePicker`, кнопку которого нажимает «Загрузить из Word» */}
      <FilePicker
        accept={DOCX}
        inputLabel={t("templates.word.file")}
        onPick={picked}
        trigger={<button ref={opener} type="button" hidden aria-hidden="true" tabIndex={-1} />}
      />
      {check && file ? (
        <CheckSheet
          check={check}
          language={language}
          applying={applying.isPending}
          error={applying.error}
          onAccept={accept}
          onCancel={reset}
        />
      ) : null}
    </>
  );
  return { download, downloadPdf, upload, busy, checking: checking.isPending, node };
}

/** Язык текста шаблона для файла и образца: RU / UZ / EN. */
export function LanguageTabs({
  value,
  onChange,
  filled,
}: {
  value: DocumentTemplateLanguage;
  onChange: (next: DocumentTemplateLanguage) => void;
  /** Языки, на которых текст уже есть; остальные помечены «нет текста» */
  filled?: readonly string[];
}) {
  const { t } = useTranslation("company");
  return (
    <Segmented<DocumentTemplateLanguage>
      aria-label={t("templates.word.language")}
      value={value}
      onChange={onChange}
      options={WORD_LANGUAGES.map((lang) => ({
        value: lang,
        label: filled && !filled.includes(lang) ? `${lang.toUpperCase()} ·` : lang.toUpperCase(),
        title: filled && !filled.includes(lang) ? t("templates.word.noText") : undefined,
      }))}
    />
  );
}

/** Кнопки «Скачать Word» · «Скачать PDF» · «Загрузить из Word» одного шаблона. */
export function TemplateWordButtons({
  template,
  word,
  canUpload,
  canPdf,
}: {
  template: WordTemplate;
  word: ReturnType<typeof useTemplateWord>;
  canUpload: boolean;
  canPdf: boolean;
}) {
  const { t } = useTranslation("company");
  return (
    <div className="pf-co-word-actions">
      <Button
        loading={word.busy === `word:${template.id}`}
        onClick={() => {
          void word.download(template);
        }}
      >
        {t("templates.word.download")}
      </Button>
      {canPdf ? (
        <Button
          loading={word.busy === `pdf:${template.id}`}
          onClick={() => {
            void word.downloadPdf(template);
          }}
        >
          {t("templates.word.downloadPdf")}
        </Button>
      ) : null}
      {canUpload ? (
        <Button
          type="primary"
          ghost
          loading={word.checking}
          onClick={() => {
            word.upload(template);
          }}
        >
          {t("templates.word.upload")}
        </Button>
      ) : null}
    </div>
  );
}
