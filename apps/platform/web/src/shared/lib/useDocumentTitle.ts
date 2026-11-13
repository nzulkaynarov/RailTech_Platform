import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { useProductName } from "./useProductName";

/** Заголовок вкладки «Раздел — <название из настроек компании>» (WCAG 2.4.2; название — задача «Н3»). */
export function useDocumentTitle(page: string | undefined): void {
  const { t } = useTranslation("shell");
  const { name } = useProductName();
  useEffect(() => {
    if (page === undefined) return;
    document.title = t("docTitle", { page, name });
  }, [page, name, t]);
}
