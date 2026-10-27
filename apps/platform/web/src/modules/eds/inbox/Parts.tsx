import { useTranslation } from "react-i18next";

import type { LetterFile } from "../../../shared/api/generated/model";
import { getDownloadLetterFileUrl } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";

function sizeLabel(bytes: number, language: string): string {
  const mega = bytes >= 1_000_000;
  return new Intl.NumberFormat(language, {
    style: "unit",
    unit: mega ? "megabyte" : "kilobyte",
    maximumFractionDigits: 1,
  }).format(mega ? bytes / 1_000_000 : Math.max(bytes / 1000, 0.1));
}

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
            {sizeLabel(file.size, i18n.language)} · {date(file.uploaded_at)}
          </span>
        </li>
      ))}
    </ul>
  );
}
