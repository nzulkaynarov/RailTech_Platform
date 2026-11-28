import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CapabilityText, CapabilityWarning } from "../../shared/api/generated/model";
import { pickText } from "./model";

/**
 * Предупреждения по фактам одной короткой строкой: «N решений держатся на одном человеке» (и «никто не решает», если есть),
 * «Показать» раскрывает список по одному в строке. Предупреждение, а не запрет: ничего не блокирует (решение владельца
 * 2026-11-26 — предупреждать, не запрещать). Показывается один раз, в таблице.
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
  const [open, setOpen] = useState(false);
  if (warnings.length === 0) return null;
  const line = (w: CapabilityWarning) => {
    const found = w.capability ? names[w.capability] : undefined;
    const capability = found ? pickText(found, i18n.language) : (w.capability ?? "");
    const key = w.code === "only_decider" && w.has_deputy ? "only_decider_deputy" : w.code;
    return t(`warnings.${key}`, { capability, person: w.person?.name ?? "" });
  };
  const onlyOne = warnings.filter((w) => w.code === "only_decider").length;
  const nobody = warnings.filter((w) => w.code === "nobody_decides").length;
  const summary = [
    onlyOne > 0 ? t("warnings.summaryOnly", { count: onlyOne }) : null,
    nobody > 0 ? t("warnings.summaryNobody", { count: nobody }) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div data-testid="cap-warnings">
      <p className="pf-cap-warn">
        {summary}{" "}
        <button
          type="button"
          className="pf-cap-warn-toggle"
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
          }}
        >
          {open ? t("warnings.hide") : t("warnings.show")}
        </button>
      </p>
      {open ? (
        <ul className="pf-cap-warn-list">
          {warnings.map((w, i) => (
            <li key={`${w.code}-${w.capability ?? ""}-${w.person?.id ?? String(i)}`}>{line(w)}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
