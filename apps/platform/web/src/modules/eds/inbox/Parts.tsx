import { useTranslation } from "react-i18next";

import type { LetterFile, RequestFile } from "../../../shared/api/generated/model";
import {
  getDownloadLetterFileUrl,
  getDownloadLetterRequestFileUrl,
} from "../../../shared/api/generated/platform-bff";
import { formatFileSize } from "../../../shared/lib/fileSize";
import { useFormat } from "../../../shared/lib/useFormat";
import { FileLinks } from "../../../shared/ui/FileLinks";

/** Вложения письма: скачивание идёт через BFF (`Content-Disposition: attachment`), файл EDS наружу не светится. */
export function Attachments({ files }: { files: readonly LetterFile[] }) {
  const { t, i18n } = useTranslation("letters");
  const { date } = useFormat();
  return (
    <ul className="pf-res-files" aria-label={t("card.files")}>
      {files.map((file) => (
        <li key={file.id}>
          <a
            className="pf-focusable pf-res-file"
            href={getDownloadLetterFileUrl(file.id)}
            download
            aria-label={t("card.download", { name: file.name })}
          >
            {file.name}
          </a>
          <span className="pf-hint">
            {formatFileSize(file.size, i18n.language)} · {date(file.uploaded_at)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Файлы, которые клиент приложил к заявке письма (СЦ-10): хранятся в ERP, скачиваются через карточку письма. */
export function RequestAttachments({
  letterId,
  number,
  files,
}: {
  letterId: string;
  number: string;
  files: readonly RequestFile[];
}) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  return (
    <div className="pf-letters-request-files">
      <h3 className="pf-hint">{t("card.requestFiles", { number })}</h3>
      <FileLinks
        label={t("card.requestFiles", { number })}
        downloadLabel={(name) => t("card.download", { name })}
        files={files.map((file) => ({
          key: file.id,
          name: file.name,
          href: getDownloadLetterRequestFileUrl(letterId, file.id),
          hint: date(file.uploaded_at),
        }))}
      />
    </div>
  );
}
