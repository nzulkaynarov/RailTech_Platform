import type { ReactNode } from "react";

import { PanelPortal } from "../../../app/shell/PanelSlot";

/**
 * Вкладка записи бокового окна (ЕД-7): «Сведения», «Маршрут», «Обсуждение», «История». Пустое содержимое вкладку не
 * занимает — вызывающий не рисует `RecordTab`, а каркас не показывает вкладку, которую никто не занял.
 */
export function RecordTab({
  tab,
  children,
}: {
  tab: "facts" | "route" | "chat" | "history";
  children: ReactNode;
}) {
  return (
    <PanelPortal tab={tab}>
      <div className="pf-dec-panel">{children}</div>
    </PanelPortal>
  );
}
