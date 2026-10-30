import { createContext, useContext, useLayoutEffect } from "react";

/** Контекст бокового окна для страниц (см. `PanelSlot.tsx`). */
export interface PanelSlotValue {
  element: HTMLElement | null;
  setElement: (element: HTMLElement | null) => void;
  /** Вкладки, которые заняли страницы: пока вкладка занята, пустое состояние каркаса не показывается */
  claimed: readonly string[];
  claim: (tab: string) => () => void;
  /** Активная вкладка окна: сообщает каркас */
  tab: string;
  setTab: (tab: string) => void;
}

export const PanelSlotContext = createContext<PanelSlotValue | null>(null);

/** Для каркаса: куда страница кладёт содержимое (`attach` — на элемент окна) и занята ли активная вкладка. */
export function usePanelSlotHost(activeTab: string) {
  const slot = useContext(PanelSlotContext);
  const setTab = slot?.setTab;
  // До отрисовки (S12): страница узнаёт активную вкладку в том же кадре, что и каркас.
  useLayoutEffect(() => {
    setTab?.(activeTab);
  }, [setTab, activeTab]);
  return {
    attach: slot?.setElement,
    claimed: slot?.claimed.includes(activeTab) ?? false,
  };
}
