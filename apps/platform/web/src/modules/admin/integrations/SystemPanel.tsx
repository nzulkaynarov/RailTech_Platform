import { useTranslation } from "react-i18next";

import { useGetSystemStatus } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { LevelTag, PanelState, PanelTitle } from "./parts";

/** Карточка «Состояние системы»: общий итог и компоненты в порядке «сбой, предупреждение, нет данных, норма». */
export function SystemPanel() {
  const { t } = useTranslation("integrations");
  const { date } = useFormat();
  const query = useGetSystemStatus();
  return (
    <div className="pf-panel-stack">
      <PanelTitle>{t("cards.system.title")}</PanelTitle>
      <PanelState query={query}>
        {(system) => (
          <>
            <p className="pf-int-sub">
              {t("system.overall")} <LevelTag level={system.status} />{" "}
              {t("system.checkedAt", { date: date(system.checked_at, "datetime") })}
            </p>
            <ul className="pf-int-list" aria-label={t("cards.system.title")}>
              {system.components.map((component) => (
                <li key={component.key}>
                  <div className="pf-int-item-head">
                    <span className="pf-int-item-title">{component.title}</span>
                    <LevelTag level={component.status} />
                  </div>
                  <p className="pf-int-sub">{component.reason}</p>
                  {component.checked_at ? (
                    <p className="pf-int-sub">
                      {t("services.checkedAt", { date: date(component.checked_at, "datetime") })}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          </>
        )}
      </PanelState>
    </div>
  );
}
