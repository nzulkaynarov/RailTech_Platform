import { Fragment } from "react";
import { useTranslation } from "react-i18next";

import type { EmployeeCapabilities } from "../../shared/api/generated/model";
import { fitItems, summaryItems } from "./areas";

/**
 * Итог словами — не больше четырёх коротких строк по областям сделки: «Ведёт», «Решает», «Отвечает за», «Не может».
 * Строка не длиннее 90 знаков и шести названий; остальное — «и ещё N» (открывает таблицу ниже). Считается из данных, без
 * произвольного текста; пустая строка не показывается.
 */
export function SummaryBox({
  data,
  person,
  onMore,
  compact = false,
}: {
  data: EmployeeCapabilities;
  /** `first` — от первого лица («Веду», «Решаю»), `third` — о сотруднике */
  person: "first" | "third";
  /** «и ещё N» открывает полную таблицу; без обработчика это просто текст */
  onMore?: () => void;
  compact?: boolean;
}) {
  const { t, i18n } = useTranslation("capabilities");
  const lines = summaryItems(data, i18n.language);
  if (lines.length === 0) return <p className="pf-hint">{t("card.nothing")}</p>;
  const scope = person === "first" ? "mine" : "card";
  return (
    <dl className={`pf-cap-sum${compact ? " pf-cap-sum-compact" : ""}`} data-testid="cap-summary">
      {lines.map((line) => {
        const label = t(`${scope}.summary.${line.key}`);
        const { shown, hidden } = fitItems(label, line.items, (n) =>
          t("card.summaryMore", { count: n }),
        );
        return (
          <div key={line.key} data-line={line.key}>
            <dt>{label}</dt>
            <dd>
              {shown.map((item, i) => (
                <Fragment key={item}>
                  {i > 0 ? ", " : ""}
                  {item}
                </Fragment>
              ))}
              {hidden > 0 ? (
                <>
                  {" "}
                  {onMore ? (
                    <button type="button" className="pf-cap-more" onClick={onMore}>
                      {t("card.summaryMore", { count: hidden })}
                    </button>
                  ) : (
                    t("card.summaryMore", { count: hidden })
                  )}
                </>
              ) : null}
              .
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
