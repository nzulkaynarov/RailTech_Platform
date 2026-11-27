import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CapabilityRow, EmployeeCapabilities } from "../../shared/api/generated/model";
import { LevelTag } from "./LevelTag";
import { pickText } from "./model";

import "./capabilities.css";

/**
 * Строки возможностей по шагам сделки: название, уровень тегом, «не всё», откуда получено. Строка раскрывается в действия
 * («что входит»): включённые обычным текстом, выключенные — зачёркнутым и словом «нет». Только чтение (ДОСТ-1).
 */
export function CapabilityRows({
  data,
  showOthers = false,
}: {
  data: EmployeeCapabilities;
  /** «Кто ещё может» — только в карточке человека у администратора */
  showOthers?: boolean;
}) {
  const { t, i18n } = useTranslation("capabilities");
  return (
    <div data-testid="cap-rows">
      {data.groups.map((group) => (
        <section
          key={group.key}
          className="pf-cap-group"
          aria-label={pickText(group.name, i18n.language)}
        >
          <h3 className="pf-cap-group-title">
            {pickText(group.name, i18n.language)}
            <span className="pf-cap-group-step">{pickText(group.step, i18n.language)}</span>
          </h3>
          <ul className="pf-cap-rows">
            {group.rows.map((row) => (
              <Row key={row.key} row={row} showOthers={showOthers} language={i18n.language} t={t} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Row({
  row,
  showOthers,
  language,
  t,
}: {
  row: CapabilityRow;
  showOthers: boolean;
  language: string;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const name = pickText(row.name, language);
  const expandable = row.level !== "none" || row.levels.length > 0;
  return (
    <li className="pf-cap-row" data-capability={row.key}>
      <button
        type="button"
        className="pf-cap-row-head"
        aria-expanded={open}
        aria-controls={bodyId}
        disabled={!expandable}
        onClick={() => {
          setOpen((value) => !value);
        }}
      >
        <span className="pf-cap-row-name">{name}</span>
        <LevelTag level={row.level} partial={row.partial} />
      </button>
      {open ? (
        <div id={bodyId} className="pf-cap-row-body">
          {row.levels.map((level) => (
            <div key={level.level}>
              <div className="pf-hint">{t(`level.${level.level}`)}</div>
              <ul className="pf-cap-actions">
                {level.actions.map((action) => (
                  <li key={action.key} className={action.on ? undefined : "pf-cap-action-off"}>
                    <span className="pf-cap-action-mark">
                      {action.on ? t("card.actionOn") : t("card.actionOff")}
                    </span>
                    <span>{pickText(action.text, language)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {row.from_roles.length > 0 ? (
            <div className="pf-hint">
              {t("card.from", { roles: row.from_roles.map((role) => role.name).join(", ") })}
            </div>
          ) : null}
          {showOthers && row.level !== "none" ? (
            <div className="pf-hint">
              {t("card.others")}:{" "}
              {row.others.length === 0
                ? t("card.noOthers")
                : `${row.others.map((p) => p.name).join(", ")}${
                    row.others_total > row.others.length
                      ? ` ${t("card.othersMore", { count: row.others_total - row.others.length })}`
                      : ""
                  }`}
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
