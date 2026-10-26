import { useTranslation } from "react-i18next";

import type { QueryStateLabels } from "../../../shared/ui/FormParts";

/** Тексты состояний запроса экрана «База знаний»: загрузка не удалась, CRM не отвечает, нет права. */
export function useKbStateLabels(): QueryStateLabels {
  const { t } = useTranslation("kb");
  return {
    retry: t("common.retry"),
    loadError: { title: t("state.loadError.title"), text: t("state.loadError.text") },
    unavailable: { title: t("state.unavailable.title"), text: t("state.unavailable.text") },
    forbidden: { title: t("state.forbidden.title"), text: t("state.forbidden.text") },
  };
}
