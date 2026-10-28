import { Button, Input } from "antd";
import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { MAX_SCAN_BYTES, scanProblem } from "./model";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp";

function sizeText(bytes: number, language: string): string {
  const mb = bytes / (1024 * 1024);
  const value =
    mb >= 1
      ? `${mb.toLocaleString(language, { maximumFractionDigits: 1 })} MB`
      : `${Math.max(1, Math.round(bytes / 1024)).toLocaleString(language)} KB`;
  return value;
}

export interface ScanFormLabels {
  label: string;
  hint: string;
  submit: string;
  choose: string;
}

/**
 * Скан подписанного документа: файл выбирается, проверяется на месте (PDF или JPG, PNG, WEBP до 20 МБ) и уходит одной
 * кнопкой «Прикрепить скан → Подписан». Окончательно тип и сигнатуру проверяет ERP; ответ с ошибкой показывается словами.
 */
export function ScanForm({
  labels,
  busy,
  error,
  onSubmit,
}: {
  labels: ScanFormLabels;
  busy: boolean;
  error: string | null;
  onSubmit: (file: File) => void;
}) {
  const { t, i18n } = useTranslation("projects");
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const problem = file ? scanProblem(file) : null;
  const ready = file !== null && problem === null;

  return (
    <form
      className="pf-fp-form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (file && ready && !busy) onSubmit(file);
      }}
    >
      <FormField
        id={id}
        label={labels.label}
        hint={`${labels.hint} (${String(MAX_SCAN_BYTES / 1024 / 1024)} MB)`}
      >
        <input
          id={id}
          ref={input}
          type="file"
          accept={ACCEPT}
          aria-describedby={`${id}-hint`}
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
          }}
        />
      </FormField>
      {file ? (
        <p className="pf-hint" role="status">
          {t("files.selected", { name: file.name, size: sizeText(file.size, i18n.language) })}
        </p>
      ) : null}
      {problem === "tooLarge" ? <p className="pf-field-error">{t("files.tooLarge")}</p> : null}
      {problem === "wrongType" || problem === "empty" ? (
        <p className="pf-field-error">{t("files.wrongType")}</p>
      ) : null}
      <ErrorNote message={error} />
      <Button
        type="primary"
        htmlType="submit"
        block
        loading={busy}
        disabled={!ready || busy}
        aria-describedby={ready ? undefined : `${id}-choose`}
      >
        {labels.submit}
      </Button>
      {ready ? null : (
        <p className="pf-hint" id={`${id}-choose`}>
          {labels.choose}
        </p>
      )}
    </form>
  );
}

export interface ReasonFormLabels {
  title: string;
  label: string;
  hint: string;
  submit: string;
  cancel: string;
  disabled: string;
}

/** Отказ или возврат со словами-причиной: причина обязательна, пока она пуста — кнопка неактивна с подписью почему. */
export function ReasonForm({
  labels,
  busy,
  error,
  onSubmit,
  onCancel,
}: {
  labels: ReasonFormLabels;
  busy: boolean;
  error: string | null;
  onSubmit: (reason: string) => void;
  onCancel: () => void;
}) {
  const id = useId();
  const [reason, setReason] = useState("");
  const text = reason.trim();
  return (
    <form
      className="pf-fp-form"
      aria-label={labels.title}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (text !== "" && !busy) onSubmit(text);
      }}
    >
      <FormField id={id} label={labels.label} hint={labels.hint}>
        <Input.TextArea
          id={id}
          value={reason}
          maxLength={1000}
          autoSize={{ minRows: 2, maxRows: 6 }}
          aria-describedby={`${id}-hint`}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
      </FormField>
      <ErrorNote message={error} />
      <div className="pf-fp-row">
        <Button
          danger
          htmlType="submit"
          loading={busy}
          disabled={text === "" || busy}
          aria-describedby={text === "" ? `${id}-disabled` : undefined}
        >
          {labels.submit}
        </Button>
        <Button onClick={onCancel} disabled={busy}>
          {labels.cancel}
        </Button>
      </div>
      {text === "" ? (
        <p className="pf-hint" id={`${id}-disabled`}>
          {labels.disabled}
        </p>
      ) : null}
    </form>
  );
}

/** Необязательная заметка к действию («Didox, № 77»). */
export function NoteField({
  label,
  hint,
  placeholder,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <FormField id={id} label={label} hint={hint}>
      <Input
        id={id}
        value={value}
        maxLength={500}
        placeholder={placeholder}
        aria-describedby={`${id}-hint`}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
    </FormField>
  );
}
