import { useTranslation } from "react-i18next";

import type { CalcSheet } from "../../../shared/api/generated/model";
import { getDownloadCalcRequestFileUrl } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { FileLinks } from "../../../shared/ui/FileLinks";
import { calcRef } from "./api";

/** Файлы, которые клиент приложил к заявке (СЦ-10); нет файлов — ничего. */
export function RequestFiles({ sheet }: { sheet: CalcSheet }) {
  const { t } = useTranslation("calc");
  const { date } = useFormat();
  const files = sheet.request.files ?? [];
  if (files.length === 0) {
    // РЕЗ-1: расчёт без резолюции ждёт файл письма клиента — честно говорим, что он ещё идёт
    return sheet.request.files_pending ? (
      <p className="pf-hint" role="status">
        {t("sheet.requestFilesPending")}
      </p>
    ) : null;
  }
  return (
    <FileLinks
      label={t("sheet.requestFiles")}
      downloadLabel={(name) => t("sheet.downloadFile", { name })}
      files={files.map((file) => ({
        key: file.id,
        name: file.name,
        href: getDownloadCalcRequestFileUrl(calcRef(sheet.number), file.id),
        hint: date(file.uploaded_at),
      }))}
    />
  );
}
