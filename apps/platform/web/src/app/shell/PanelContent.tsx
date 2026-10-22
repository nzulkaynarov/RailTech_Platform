import { useTranslation } from "react-i18next";

import { NotificationsTab, TodayTab } from "../../modules/dashboard/ActivityPanel";
import type { ModuleCode } from "../../shared/api/generated/model";
import { EmptyState } from "../../shared/ui/EmptyState";

/**
 * Содержимое активной вкладки бокового окна. «Моя очередь» показывает ленту «Сегодня» и уведомления (SPEC-v3 §7.1);
 * остальные вкладки до своих экранов (фазы P2+) — пустое состояние словами.
 */
export function PanelContent({
  module,
  section,
  tab,
}: {
  module: ModuleCode | undefined;
  section: string | undefined;
  tab: string;
}) {
  const { t } = useTranslation("modules");
  if (module === "dashboard" && section === "queue") {
    if (tab === "today") return <TodayTab />;
    if (tab === "notifications") return <NotificationsTab />;
  }
  return (
    <EmptyState level={3} compact title={t(`panel.${tab}.title`)} text={t(`panel.${tab}.text`)} />
  );
}
