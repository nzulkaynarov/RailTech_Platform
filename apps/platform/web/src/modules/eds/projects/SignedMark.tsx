import { Button, Input, Upload } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { formatFileSize } from "../../../shared/lib/fileSize";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { scanProblem } from "./model";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp";

/**
 * «Отметить: подписан» (ДП-1): договор ждёт подписания вне Платформы; сотрудник отмечает подпись сканом ИЛИ заметкой.
 * Файл проверяется на месте (PDF или изображение до 20 МБ), окончательно — ERP. Срок договора ERP считает в момент отметки.
 */
export function SignedMark({
  busy,
  error,
  onScan,
  onNote,
}: {
  busy: boolean;
  error: string | null;
  onScan: (file: File) => void;
  onNote: (note: string) => void;
}) {
  const { t, i18n } = useTranslation("projects");
  const ids = { file: useId(), note: useId() };
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const problem = file ? scanProblem(file) : null;
  const ready = (file !== null && problem === null) || (file === null && note.trim() !== "");

  return (
    <form
      className="pf-fp-form"
      aria-label={t("contract.sign.title")}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (busy || !ready) return;
        if (file) onScan(file);
        else onNote(note.trim());
      }}
    >
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("contract.sign.hint")}
      </p>
      <FormField id={ids.file} label={t("contract.scan.label")} hint={t("contract.scan.hint")}>
        <Upload
          id={ids.file}
          accept={ACCEPT}
          maxCount={1}
          beforeUpload={(chosen) => {
            setFile(chosen);
            return false;
          }}
          onRemove={() => {
            setFile(null);
          }}
          fileList={file ? [{ uid: "scan", name: file.name, status: "done" }] : []}
          locale={{ removeFile: t("files.remove") }}
        >
          <Button>{t("files.choose")}</Button>
        </Upload>
      </FormField>
      {file ? (
        <p className="pf-hint" role="status">
          {t("files.selected", { name: file.name, size: formatFileSize(file.size, i18n.language) })}
        </p>
      ) : null}
      {problem === "tooLarge" ? <p className="pf-field-error">{t("files.tooLarge")}</p> : null}
      {problem === "wrongType" || problem === "empty" ? (
        <p className="pf-field-error">{t("files.wrongType")}</p>
      ) : null}
      <FormField
        id={ids.note}
        label={t("contract.sign.noteLabel")}
        hint={t("contract.sign.noteHint")}
      >
        <Input.TextArea
          id={ids.note}
          value={note}
          rows={2}
          maxLength={500}
          aria-describedby={`${ids.note}-hint`}
          onChange={(event) => {
            setNote(event.target.value);
          }}
        />
      </FormField>
      <ErrorNote message={error} />
      <Button type="primary" htmlType="submit" block loading={busy} disabled={!ready || busy}>
        {t("contract.action.mark_signed")}
      </Button>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("contract.sign.term")}
      </p>
    </form>
  );
}
