import { Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { downloadFile } from "../../../shared/api/download";
import { ApiError } from "../../../shared/api/errors";
import {
  getDownloadCrmRequestFileUrl,
  useUploadCrmRequestFile,
} from "../../../shared/api/generated/platform-bff";
import { FilePicker } from "../../../shared/ui/FileField";
import { MAX_FILE_BYTES } from "../../eds/documents/fileSize";
import { reasonError } from "../common/errors";
import { noteContext, type NoteKind } from "./callNote";
import type { LetterFile } from "./formModel";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.gif,.webp,.tif,.tiff,.doc,.docx,.xls,.xlsx,.ppt,.pptx";

/**
 * Письмо на имя директора: файл уходит в EDS сразу после выбора (BFF `POST /crm/request-files` от имени менеджера), в
 * заявку — только id готового файла. Больше 25 МБ не отправляется вовсе; тип проверяет сервер.
 *
 * Заявка по звонку (СЦ-6): вместо файла основанием служит записка о звонке, которую собирает система (`callNote`) —
 * «приложена · Открыть · Заменить файлом». Кнопка «Основание — звонок» есть, пока файла нет (и после неудачной сборки).
 */
export function LetterField({
  id,
  value,
  onChange,
  callNote,
}: {
  id: string;
  value: LetterFile | null;
  onChange: (value: LetterFile | null) => void;
  /** Основание по звонку возможно: сборка записки и причина, по которой её пока нельзя заказать */
  callNote?: { onStart: () => void; blockedReason?: string | null; kind?: NoteKind };
}) {
  const { t } = useTranslation("request");
  const upload = useUploadCrmRequestFile();
  const [openError, setOpenError] = useState<string | null>(null);
  const note = value?.kind === "call_note";
  const noteDone = note && value.status === "done";
  const context = noteContext(callNote?.kind ?? "call");
  const noteAction = callNote && (!value || (note && value.status === "error"));

  const pick = (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      onChange({ name: file.name, status: "error", error: t("letter.tooLarge") });
      return;
    }
    onChange({ name: file.name, status: "uploading" });
    upload
      .mutateAsync({ data: { file } })
      .then((ref) => {
        onChange({ name: ref.name, status: "done", id: ref.id });
      })
      .catch((error: unknown) => {
        const unsupported = error instanceof ApiError && error.status === 415;
        onChange({
          name: file.name,
          status: "error",
          error: unsupported
            ? t("letter.unsupported")
            : t("letter.failed", { reason: reasonError(t, "request:errors", error) }),
        });
      });
  };

  return (
    <div className="pf-fp-stack" style={{ gap: 8 }}>
      <div>
        <FilePicker
          id={id}
          accept={ACCEPT}
          aria-describedby={`${id}-hint`}
          buttonLabel={
            noteDone
              ? t("letter.replaceNote")
              : value && !(note && value.status === "error")
                ? t("ui:file.replace")
                : undefined
          }
          onPick={(files) => {
            pick(files[0]);
          }}
        />
      </div>
      {noteAction ? (
        <div className="pf-fp-row" style={{ alignItems: "center" }}>
          <Button
            size="small"
            disabled={Boolean(callNote.blockedReason)}
            aria-describedby={callNote.blockedReason ? `${id}-note-hint` : undefined}
            onClick={callNote.onStart}
          >
            {note ? t("letter.noteRetry") : t("letter.callBasis", { context })}
          </Button>
          {callNote.blockedReason ? (
            <span className="pf-hint" id={`${id}-note-hint`}>
              {callNote.blockedReason}
            </span>
          ) : null}
        </div>
      ) : null}
      {value ? (
        <div className="pf-fp-row" style={{ alignItems: "center" }}>
          {value.status === "uploading" ? (
            <span className="pf-hint" role="status">
              {note ? t("letter.noteBuilding", { context }) : t("letter.uploading")}
            </span>
          ) : null}
          {value.status === "done" ? (
            <span role="status">
              {note
                ? t("letter.noteAttached", { context })
                : t("letter.uploaded", { name: value.name })}
            </span>
          ) : null}
          {noteDone && value.id ? (
            <Button
              type="link"
              size="small"
              style={{ padding: 0, height: "auto" }}
              aria-label={t("letter.openNote", { name: value.name })}
              onClick={() => {
                setOpenError(null);
                downloadFile(getDownloadCrmRequestFileUrl(value.id ?? ""), value.name).catch(() => {
                  setOpenError(t("letter.openFailed"));
                });
              }}
            >
              {t("letter.open")}
            </Button>
          ) : null}
          {value.status === "error" ? (
            <span className="pf-req-error" role="alert">
              {value.error}
            </span>
          ) : null}
          {value.status === "uploading" ? null : (
            <Button
              type="link"
              size="small"
              style={{ padding: 0, height: "auto" }}
              onClick={() => {
                onChange(null);
              }}
            >
              {t("letter.remove")}
            </Button>
          )}
        </div>
      ) : null}
      {openError ? (
        <span className="pf-req-error" role="alert">
          {openError}
        </span>
      ) : null}
    </div>
  );
}
