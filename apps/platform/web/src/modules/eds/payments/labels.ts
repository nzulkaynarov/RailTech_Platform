import { useTranslation } from "react-i18next";

import type { QueryStateLabels } from "../../../shared/ui/FormParts";

/** Тексты состояний запроса экрана «Счета и оплаты»: не загрузилось, сервис не отвечает, нет права. */
export function useStateLabels(): QueryStateLabels {
  const { t } = useTranslation("payments");
  return {
    retry: t("state.retry"),
    loadError: { title: t("state.loadError.title"), text: t("state.loadError.text") },
    unavailable: { title: t("state.unavailable.title"), text: t("state.unavailable.text") },
    forbidden: { title: t("state.forbidden.title"), text: t("state.forbidden.text") },
  };
}
