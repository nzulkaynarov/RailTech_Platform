import { App, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { FileNotReadyError, downloadFile } from "../../../shared/api/download";
import { reasonText } from "./errors";

export interface FileItem {
  url: string;
  label: string;
  /** Имя на случай, если сервер не прислал своё */
  name: string;
}

/**
 * Файлы документа проекта (наш PDF и скан подписанного) кнопками-ссылками. Файл берётся запросом с cookie сессии
 * (`downloadFile`): PDF ещё готовится (202) — сообщение «повторите через несколько секунд», а не файл-пустышка с JSON.
 */
export function FileLinks({ items }: { items: readonly (FileItem | null)[] }) {
  const { t } = useTranslation("projects");
  const { message } = App.useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const shown = items.filter((item): item is FileItem => item !== null);
  if (shown.length === 0) return null;

  const download = async (item: FileItem) => {
    setBusy(item.url);
    try {
      await downloadFile(item.url, item.name);
    } catch (error) {
      void message.error(
        error instanceof FileNotReadyError ? t("files.generating") : reasonText(t, error),
      );
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="pf-fp-row" role="group" aria-label={t("card.documents.title")}>
      {shown.map((item) => (
        <Button
          key={item.url}
          size="small"
          loading={busy === item.url}
          onClick={() => {
            void download(item);
          }}
        >
          {item.label}
        </Button>
      ))}
    </div>
  );
}
