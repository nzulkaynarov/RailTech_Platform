import { useTranslation } from "react-i18next";

import { ServiceVersions } from "../../../features/about/AboutPanel";
import { useAbout, useReleaseText } from "../../../features/about/release";
import { useGetSystemStatus } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { LevelTag, PanelState, PanelTitle } from "./parts";

/**
 * Карточка «Состояние системы»: общий итог и компоненты в порядке «сбой, предупреждение, нет данных, норма»; ниже — версия
 * Платформы и версии сервисов BFF, CRM, ERP, EDS, если их health её сообщает (W-REL).
 */
export function SystemPanel() {
  const { t } = useTranslation("integrations");
  const { date } = useFormat();
  const query = useGetSystemStatus();
  const about = useAbout();
  const release = useReleaseText();
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
      {about.data ? (
        <section aria-labelledby="pf-system-versions">
          <h3 id="pf-system-versions" className="pf-int-item-title" style={{ margin: "8px 0 4px" }}>
            {t("system.versions")}
          </h3>
          <p className="pf-int-sub" data-testid="system-release">
            {release}
          </p>
          <ServiceVersions services={about.data.services} />
        </section>
      ) : null}
    </div>
  );
}
