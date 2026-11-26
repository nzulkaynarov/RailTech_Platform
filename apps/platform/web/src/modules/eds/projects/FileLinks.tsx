import { Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DefinitionItem } from "../../../shared/ui/DefinitionList";
import { DocumentPeek } from "../../../shared/ui/DocumentViewer/DocumentPeek";

export interface FileItem {
  url: string;
  label: string;
  /** Имя на случай, если сервер не прислал своё */
  name: string;
}

/**
 * Файлы документа проекта (наш PDF и скан подписанного): одно действие на файл — открыть в боковом окне просмотра
 * (`DocumentPeek`); «Скачать» и «На весь экран» — внутри просмотра. Файл ещё готовится (202) — слова «повторите через
 * несколько секунд» и кнопка «Скачать» в самом окне. `about` — «О документе» для слоя на весь экран.
 */
export function FileLinks({
  items,
  about,
}: {
  items: readonly (FileItem | null)[];
  about?: readonly DefinitionItem[];
}) {
  const { t } = useTranslation("projects");
  const [opened, setOpened] = useState<FileItem | null>(null);
  const shown = items.filter((item): item is FileItem => item !== null);
  if (shown.length === 0) return null;
  return (
    <div className="pf-fp-row" role="group" aria-label={t("card.documents.title")}>
      {shown.map((item) => (
        <Button
          key={item.url}
          size="small"
          aria-haspopup="dialog"
          onClick={() => {
            setOpened(item);
          }}
        >
          {item.label}
        </Button>
      ))}
      {opened ? (
        <DocumentPeek
          url={opened.url}
          title={opened.label}
          fallbackName={opened.name}
          {...(about ? { about } : {})}
          onClose={() => {
            setOpened(null);
          }}
        />
      ) : null}
    </div>
  );
}
