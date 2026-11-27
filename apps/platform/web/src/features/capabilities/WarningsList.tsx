import { Alert } from "antd";
import { useTranslation } from "react-i18next";

import type { CapabilityText, CapabilityWarning } from "../../shared/api/generated/model";
import { pickText } from "./model";

/**
 * Предупреждения по фактам: «решает один человек, замещающего нет», «никто не решает», «виза есть, права подписи нет».
 * Предупреждение, а не запрет: ничего не блокирует (решение владельца 2026-11-26 — предупреждать, не запрещать).
 */
export function WarningsList({
  warnings,
  names,
}: {
  warnings: readonly CapabilityWarning[];
  /** Названия строк по ключу; в карточке берутся из её строк, в таблице — из каталога таблицы */
  names: Readonly<Record<string, CapabilityText>>;
}) {
  const { t, i18n } = useTranslation("capabilities");
  if (warnings.length === 0) return null;
  return (
    <Alert
      type="warning"
      showIcon
      style={{ margin: "12px 0" }}
      message={t("warnings.title")}
      description={
        <ul style={{ margin: 0, paddingLeft: 16 }} data-testid="cap-warnings">
          {warnings.map((w, i) => {
            const found = w.capability ? names[w.capability] : undefined;
            const capability = found ? pickText(found, i18n.language) : (w.capability ?? "");
            const key = w.code === "only_decider" && w.has_deputy ? "only_decider_deputy" : w.code;
            return (
              <li key={`${w.code}-${w.capability ?? ""}-${w.person?.id ?? String(i)}`}>
                {t(`warnings.${key}`, { capability, person: w.person?.name ?? "" })}
              </li>
            );
          })}
        </ul>
      }
    />
  );
}
