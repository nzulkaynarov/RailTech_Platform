import { useTranslation } from "react-i18next";

import type { CapabilityText, CapabilityWarning } from "../../shared/api/generated/model";
import { pickText } from "./model";

/**
 * Предупреждения по фактам одной строкой: «решает один человек, замещающего нет», «никто не решает». Предупреждение, а не
 * запрет: ничего не блокирует (решение владельца 2026-11-26 — предупреждать, не запрещать). Показывается один раз, в таблице.
 */
export function WarningsList({
  warnings,
  names,
}: {
  warnings: readonly CapabilityWarning[];
  /** Названия строк по ключу из каталога таблицы */
  names: Readonly<Record<string, CapabilityText>>;
}) {
  const { t, i18n } = useTranslation("capabilities");
  if (warnings.length === 0) return null;
  return (
    <p className="pf-cap-warn" data-testid="cap-warnings">
      <strong>{t("warnings.title")}</strong>{" "}
      {warnings.map((w, i) => {
        const found = w.capability ? names[w.capability] : undefined;
        const capability = found ? pickText(found, i18n.language) : (w.capability ?? "");
        const key = w.code === "only_decider" && w.has_deputy ? "only_decider_deputy" : w.code;
        return (
          <span key={`${w.code}-${w.capability ?? ""}-${w.person?.id ?? String(i)}`}>
            {i > 0 ? " · " : ""}
            {t(`warnings.${key}`, { capability, person: w.person?.name ?? "" })}
          </span>
        );
      })}
    </p>
  );
}
