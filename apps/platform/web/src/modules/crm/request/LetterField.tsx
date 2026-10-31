import { Button } from "antd";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import { useUploadCrmRequestFile } from "../../../shared/api/generated/platform-bff";
import { FilePicker } from "../../../shared/ui/FileField";
import { MAX_FILE_BYTES } from "../../eds/documents/fileSize";
import { reasonError } from "../common/errors";
import type { LetterFile } from "./formModel";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.gif,.webp,.tif,.tiff,.doc,.docx,.xls,.xlsx,.ppt,.pptx";

/**
 * Письмо на имя директора: файл уходит в EDS сразу после выбора (BFF `POST /crm/request-files` от имени менеджера), в
 * заявку — только id готового файла. Больше 25 МБ не отправляется вовсе; тип проверяет сервер.
 */
export function LetterField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: LetterFile | null;
  onChange: (value: LetterFile | null) => void;
}) {
  const { t } = useTranslation("request");
  const upload = useUploadCrmRequestFile();

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
          buttonLabel={value ? t("ui:file.replace") : undefined}
          onPick={(files) => {
            pick(files[0]);
          }}
        />
      </div>
      {value ? (
        <div className="pf-fp-row" style={{ alignItems: "center" }}>
          {value.status === "uploading" ? (
            <span className="pf-hint" role="status">
              {t("letter.uploading")}
            </span>
          ) : null}
          {value.status === "done" ? (
            <span role="status">{t("letter.uploaded", { name: value.name })}</span>
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
    </div>
  );
}
