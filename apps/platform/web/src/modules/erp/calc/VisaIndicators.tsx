import { useTranslation } from "react-i18next";

import type { CalcVisaIndicators, CalcVisaState } from "../../../shared/api/generated/model";
import { StatusTag } from "../../../shared/ui/StatusTag";

const GROUPS = ["stock", "supply", "engineer"] as const;
const TONE: Record<CalcVisaState, "green" | "gold" | "default"> = {
  done: "green",
  waiting: "gold",
  none: "default",
};

/**
 * Три индикатора виз заявки (SPEC-v3 §7.4): склад — товары со склада, снабжение — товары под заказ, гл. инженер — услуги.
 * Состояние всегда словом («Склад ✓», «Гл. инженер · ждёт»), цвет только дублирует его.
 */
export function VisaIndicators({ visas }: { visas: CalcVisaIndicators }) {
  const { t } = useTranslation("calc");
  return (
    <ul className="pf-calc-visas" aria-label={t("list.columns.visas")}>
      {GROUPS.map((group) => {
        const state = visas[group];
        const name = t(`groups.${group}`);
        return (
          <li key={group}>
            <StatusTag tone={TONE[state]}>
              <span aria-hidden="true">{t(`visaState.${state}`, { group: name })}</span>
              <span className="pf-sr-only">{t(`visaState.${state}Label`, { group: name })}</span>
            </StatusTag>
          </li>
        );
      })}
    </ul>
  );
}
