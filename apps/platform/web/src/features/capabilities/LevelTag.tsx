import { useTranslation } from "react-i18next";

import type { CapabilityLevel } from "../../shared/api/generated/model";

import "./capabilities.css";

/**
 * Уровень возможности словом, не цветом: «Нет» — серый, «Смотреть» — нейтральный, «Работать» — синий, «Решать» — тёмно-синий
 * (контраст текста не ниже 4,5:1). «не всё» — отдельная пометка рядом (ДОСТ-1).
 */
export function LevelTag({
  level,
  partial = false,
}: {
  level: CapabilityLevel;
  partial?: boolean;
}) {
  const { t } = useTranslation("capabilities");
  return (
    <span className="pf-cap-levelwrap">
      <span className={`pf-cap-level pf-cap-level-${level}`}>{t(`level.${level}`)}</span>
      {partial ? (
        <span className="pf-cap-partial" title={t("partialHint")}>
          {t("partial")}
        </span>
      ) : null}
    </span>
  );
}
