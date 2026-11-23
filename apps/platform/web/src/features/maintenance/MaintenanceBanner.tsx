import { Button } from "antd";
import { useTranslation } from "react-i18next";

import { WarningIcon } from "../../shared/ui/icons";
import { useMaintenanceNotice } from "./useMaintenanceNotice";

import "./maintenance.css";

/**
 * Плашка планового обновления над шапкой (DECISIONS 2026-11-23): за 30 минут до начала — «Обновление Платформы в 19:15 —
 * работа прервётся на 2–3 минуты. Сохраните изменения.», во время работ — «Идёт обновление…». Срочное исправление
 * (`kind: urgent`) — те же места, другое слово. Скрывается на 10 минут, в последние 5 возвращается. `role="status"`.
 */
export function MaintenanceBanner() {
  const { t } = useTranslation("shell");
  const { view, dismiss } = useMaintenanceNotice();
  if (!view) return null;
  const urgent = view.kind === "urgent" ? "Urgent" : "";
  const text =
    view.phase === "soon"
      ? t(`maintenance.soon${urgent}`, {
          time: view.time,
          duration: t("maintenance.minutes", {
            count: view.to,
            range:
              view.from === view.to ? String(view.to) : `${String(view.from)}–${String(view.to)}`,
          }),
        })
      : t(`maintenance.running${urgent}`);
  return (
    <div className="pf-maint" role="status">
      <span className="pf-maint-icon">
        <WarningIcon />
      </span>
      <span className="pf-maint-text">{text}</span>
      {view.dismissible ? (
        <Button size="small" onClick={dismiss}>
          {t("maintenance.hide")}
        </Button>
      ) : null}
    </div>
  );
}
