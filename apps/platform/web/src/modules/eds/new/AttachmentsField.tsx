import { Button } from "antd";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import { useUploadEdsDocumentFile } from "../../../shared/api/generated/platform-bff";
import { reasonText } from "../documents/errors";
import { MAX_FILE_BYTES, formatFileSize } from "../documents/fileSize";
import type { Attachment } from "./formModel";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.gif,.webp,.tif,.tiff,.doc,.docx,.xls,.xlsx,.ppt,.pptx";

/**
 * Вложения документа: файл уходит в EDS сразу после выбора (BFF → EDS `/files`), в документ привязывается при создании или
 * сохранении. Размер и тип проверяет сервер (25 МБ; PDF, изображения, документы Office); слишком большой файл не
 * отправляется вовсе. Загруженный в черновик файл снять нельзя — EDS хранит вложения, а не заменяет их.
 */
export function AttachmentsField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: readonly Attachment[];
  onChange: (updater: (prev: Attachment[]) => Attachment[]) => void;
}) {
  const { t, i18n } = useTranslation("documents");
  const upload = useUploadEdsDocumentFile();
  const input = useRef<HTMLInputElement>(null);
  const counter = useRef(0);

  const patch = (key: string, change: Partial<Attachment>) => {
    onChange((prev) => prev.map((item) => (item.key === key ? { ...item, ...change } : item)));
  };

  const send = (key: string, file: File) => {
    // Несколько файлов — несколько одновременных загрузок: у каждой свой результат (`mutate` вызвал бы колбэки только последней).
    upload
      .mutateAsync({ data: { file } })
      .then((ref) => {
        patch(key, { status: "done", id: ref.id, size: ref.size });
      })
      .catch((error: unknown) => {
        const unsupported = error instanceof ApiError && error.status === 415;
        patch(key, {
          status: "error",
          error: unsupported
            ? t("form.files.unsupported")
            : t("form.files.failed", { reason: reasonText(t, error) }),
        });
      });
  };

  const pick = (list: FileList | null) => {
    const files = Array.from(list ?? []);
    if (input.current) input.current.value = "";
    if (files.length === 0) return;
    const items = files.map((file) => {
      counter.current += 1;
      const tooLarge = file.size > MAX_FILE_BYTES;
      const item: Attachment = {
        key: `new-${String(counter.current)}`,
        name: file.name,
        size: file.size,
        status: tooLarge ? "error" : "uploading",
        ...(tooLarge ? { error: t("form.files.tooLarge") } : {}),
      };
      return { item, file };
    });
    onChange((prev) => [...prev, ...items.map((entry) => entry.item)]);
    for (const { item, file } of items) if (item.status === "uploading") send(item.key, file);
  };

  return (
    <div className="pf-fp-stack" style={{ gap: 8 }}>
      <input
        id={id}
        ref={input}
        type="file"
        multiple
        accept={ACCEPT}
        aria-describedby={`${id}-hint`}
        onChange={(event) => {
          pick(event.target.files);
        }}
      />
      {value.length > 0 ? (
        <ul className="pf-doc-files" aria-label={t("form.files.list")}>
          {value.map((item) => (
            <li key={item.key} className="pf-doc-file">
              <span className="pf-doc-file-name">{item.name}</span>
              <span className="pf-hint">{formatFileSize(item.size, i18n.language)}</span>
              {item.status === "uploading" ? (
                <span className="pf-hint" role="status">
                  {t("form.files.uploading")}
                </span>
              ) : null}
              {item.status === "done" ? (
                <span className="pf-hint">
                  {item.existing ? t("form.files.attached") : t("form.files.uploaded")}
                </span>
              ) : null}
              {item.status === "error" ? (
                <span className="pf-field-error" role="alert">
                  {item.error}
                </span>
              ) : null}
              {item.existing ? null : (
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0, height: "auto" }}
                  aria-label={t("form.files.remove", { name: item.name })}
                  onClick={() => {
                    onChange((prev) => prev.filter((other) => other.key !== item.key));
                  }}
                >
                  ×
                </Button>
              )}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
