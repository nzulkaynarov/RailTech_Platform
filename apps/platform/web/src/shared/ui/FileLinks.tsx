import "./ui.css";

export type FileLink = {
  key: string | number;
  name: string;
  href: string;
  /** Подсказка под именем: размер, дата. */
  hint?: string;
};

/** Файлы для скачивания через BFF (`Content-Disposition: attachment`): имя — ссылка, под ним подсказка. */
export function FileLinks({
  files,
  label,
  downloadLabel,
}: {
  files: readonly FileLink[];
  label: string;
  downloadLabel: (name: string) => string;
}) {
  return (
    <ul className="pf-file-links" aria-label={label}>
      {files.map((file) => (
        <li key={file.key}>
          <a
            className="pf-focusable pf-file-link"
            href={file.href}
            download
            aria-label={downloadLabel(file.name)}
          >
            {file.name}
          </a>
          {file.hint ? <span className="pf-hint">{file.hint}</span> : null}
        </li>
      ))}
    </ul>
  );
}
