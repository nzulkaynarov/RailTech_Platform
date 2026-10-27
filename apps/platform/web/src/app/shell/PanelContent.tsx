import { useTranslation } from "react-i18next";

import { isStubSection } from "../../modules/bridge";
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
  const { t } = useTranslation(["modules", "bridge"]);
  if (module === "dashboard" && section === "queue") {
    if (tab === "today") return <TodayTab />;
    if (tab === "notifications") return <NotificationsTab />;
  }
  // Раздел-заглушка (W15-H1): «Объект не выбран. Выберите строку в таблице» рядом с заглушкой — неправда, таблицы нет.
  if (module && section && isStubSection(module, section)) {
    return (
      <EmptyState level={3} compact title={t("bridge:panel.title")} text={t("bridge:panel.text")} />
    );
  }
  return (
    <EmptyState
      level={3}
      compact
      title={t(`modules:panel.${tab}.title`)}
      text={t(`modules:panel.${tab}.text`)}
    />
  );
}
