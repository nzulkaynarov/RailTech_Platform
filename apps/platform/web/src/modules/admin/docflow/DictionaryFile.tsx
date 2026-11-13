import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Modal, Upload } from "antd";
import type { TFunction } from "i18next";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type {
  Dictionary,
  DictionaryImportResult,
  DictionaryImportRow,
} from "../../../shared/api/generated/model";
import {
  getExportDictionaryUrl,
  getListDictionaryItemsQueryKey,
  importDictionary,
} from "../../../shared/api/generated/platform-bff";
import { downloadFile } from "../../../shared/api/download";
import { localName } from "../../eds/dictionaries";
import { DataTable } from "../../../shared/ui/DataTable/DataTable";

const ACCEPT =
  ".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv";

function errorText(t: TFunction, failure: unknown): string {
  if (failure instanceof ApiError) return failure.message || t("settings.dict.file.failed");
  return t("settings.dict.file.failed");
}

/** Подпись столбца файла: базовые — словами, поля вида — их названием на языке сотрудника. */
function columnLabel(t: TFunction, dictionary: Dictionary, key: string, language: string): string {
  const attr = dictionary.attrs.find((a) => a.key === key);
  if (attr) return localName(attr.name, language);
  return t(`settings.dict.file.columns.${key}`, { defaultValue: key });
}

function rowText(
  t: TFunction,
  dictionary: Dictionary,
  row: DictionaryImportRow,
  language: string,
): string {
  const label = (key: string) => columnLabel(t, dictionary, key, language);
  if (row.action === "error") {
    return row.errors
      .map((e) =>
        t(`settings.dict.file.reasons.${e.reason}`, {
          field: label(e.field),
          defaultValue: `${label(e.field)}: ${e.reason}`,
        }),
      )
      .join("; ");
  }
  if (row.action === "update") return row.fields.map(label).join(", ");
  return "";
}

/**
 * «Скачать» и «Загрузить» у справочника (решение владельца 2026-11-11): шаблон — это выгрузка списка; загрузка сначала
 * проверяется без записи, «Применить» доступно, только если в файле нет ошибок. Удалять файлом нельзя.
 */
export function DictionaryFile({
  dictionary,
  readOnly,
}: {
  dictionary: Dictionary;
  readOnly: boolean;
}) {
  const { t, i18n } = useTranslation("letters");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const kind = dictionary.kind;
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<DictionaryImportResult | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const title = localName(dictionary.name, i18n.language);

  const close = () => {
    setFile(null);
    setResult(null);
    setError(null);
  };
  const download = async () => {
    try {
      await downloadFile(getExportDictionaryUrl(kind, { format: "xlsx" }), `${kind}.xlsx`);
    } catch (failure) {
      void message.error(errorText(t, failure));
    }
  };
  const run = async (picked: File, dryRun: boolean) => {
    setPending(true);
    setError(null);
    try {
      const next = await importDictionary(kind, picked, { dry_run: dryRun });
      setResult(next);
      if (next.applied) {
        void queryClient.invalidateQueries({ queryKey: getListDictionaryItemsQueryKey(kind) });
        void message.success(
          t("settings.dict.file.done", { added: next.added, updated: next.updated }),
        );
        close();
      }
    } catch (failure) {
      setResult(null);
      setError(errorText(t, failure));
    } finally {
      setPending(false);
    }
  };
  const changes = result ? result.added + result.updated : 0;
  const shown = result ? result.rows.filter((r) => r.action !== "unchanged") : [];

  return (
    <>
      <Button onClick={() => void download()}>{t("settings.dict.file.download")}</Button>
      <Upload
        accept={ACCEPT}
        showUploadList={false}
        disabled={readOnly}
        beforeUpload={(picked) => {
          setFile(picked);
          void run(picked, true);
          return false;
        }}
      >
        <Button disabled={readOnly}>{t("settings.dict.file.upload")}</Button>
      </Upload>
      <Modal
        open={file !== null}
        width={720}
        title={t("settings.dict.file.title", { name: title })}
        onCancel={close}
        footer={null}
        destroyOnHidden
      >
        <div className="pf-mail-actions">
          {error ? <Alert type="error" showIcon role="alert" message={error} /> : null}
          {result ? (
            <Alert
              type={result.failed > 0 ? "warning" : "info"}
              showIcon
              role="status"
              message={t("settings.dict.file.summary", {
                added: result.added,
                updated: result.updated,
                unchanged: result.unchanged,
                failed: result.failed,
              })}
            />
          ) : null}
          {shown.length > 0 ? (
            <DataTable<DictionaryImportRow>
              tableId="admin.docflow.dictionaryFile"
              caption={t("settings.dict.file.title", { name: title })}
              scrollLabel={t("settings.dict.file.title", { name: title })}
              rows={shown}
              rowKey={(row) => String(row.line)}
              pageSize={20}
              columns={[
                {
                  id: "line",
                  header: t("settings.dict.file.line"),
                  width: 72,
                  cell: (row) => row.line,
                },
                {
                  id: "name",
                  header: t("settings.dict.name"),
                  width: null,
                  cell: (row) => row.name,
                },
                {
                  id: "action",
                  header: t("settings.dict.file.action"),
                  width: null,
                  cell: (row) => t(`settings.dict.file.actions.${row.action}`),
                },
                {
                  id: "details",
                  header: t("settings.dict.file.details"),
                  width: null,
                  cell: (row) => rowText(t, dictionary, row, i18n.language),
                },
              ]}
            />
          ) : null}
          <div className="pf-fp-row">
            <Button
              type="primary"
              loading={pending}
              disabled={!file || !result || result.failed > 0 || changes === 0}
              onClick={() => {
                if (file) void run(file, false);
              }}
            >
              {t("settings.dict.file.apply")}
            </Button>
            <Button onClick={close}>{t("settings.dict.file.cancel")}</Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
