import type { TFunction } from "i18next";

import type { QueryStateLabels } from "../../../shared/ui/FormParts";

/** Тексты состояний загрузки списков и карточек экрана «Номенклатура и поставщики» (`catalog:state.*`). */
export function queryLabels(t: TFunction): QueryStateLabels {
  return {
    retry: t("state.retry"),
    loadError: { title: t("state.loadError.title"), text: t("state.loadError.text") },
    unavailable: { title: t("state.unavailable.title"), text: t("state.unavailable.text") },
    forbidden: { title: t("state.forbidden.title"), text: t("state.forbidden.text") },
  };
}
