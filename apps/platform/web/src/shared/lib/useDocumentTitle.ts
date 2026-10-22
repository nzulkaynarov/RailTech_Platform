import { useEffect } from "react";
import { useTranslation } from "react-i18next";

/** Заголовок вкладки «Раздел — RailTech Platform» (WCAG 2.4.2). */
export function useDocumentTitle(page: string): void {
  const { t } = useTranslation("shell");
  useEffect(() => {
    document.title = t("docTitle", { page });
  }, [page, t]);
}
