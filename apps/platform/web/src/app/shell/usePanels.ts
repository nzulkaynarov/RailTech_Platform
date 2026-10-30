import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

import type { SectionConfig } from "../../modules/types";
import { DEFAULT_TABS } from "../../modules/types";
import {
  panelsKey,
  usePanelsStore,
  type PanelLayoutMode,
  type PanelWidthPreset,
} from "./panelsStore";
import { useViewport } from "./useViewport";

export interface Panels {
  menuOpen: boolean;
  panelOpen: boolean;
  panelMode: PanelLayoutMode;
  panelWidth: PanelWidthPreset;
  tab: string;
  tabs: readonly string[];
  toggleMenu: () => void;
  togglePanel: () => void;
  setPanelOpen: (open: boolean) => void;
  setPanelMode: (mode: PanelLayoutMode) => void;
  setPanelWidth: (width: PanelWidthPreset) => void;
  setTab: (tab: string) => void;
}

/**
 * Подменю: запоминается на пользователя и раздел.
 * Боковое окно: открыто только по адресу — `?panel=open`; на карточке объекта (`:id`) на широком экране открыто,
 * пока не закрыто явно (`?panel=closed`).
 * Настройки отображения (режим overlay/docked, ширина default/wide, последняя вкладка lastTab)
 * сохраняются в panelsStore (localStorage ключ rt-pf-panels-v2).
 */
export function usePanels(
  userId: string,
  section: SectionConfig | undefined,
  fallbackOpen = false,
): Panels {
  const { wide, menuWide } = useViewport();
  const [params, setParams] = useSearchParams();
  const key = panelsKey(userId, section?.path.split("?")[0] ?? "-");
  const entry = usePanelsStore((s) => s.entries[key]);
  const patch = usePanelsStore((s) => s.patch);

  const tabs = useMemo(() => (section?.tabs ?? DEFAULT_TABS).map((t) => t.key), [section]);

  // Открытие панели: в списках определяется ?panel=open в URL; на карточке объекта (:id) — fallbackOpen на широком экране
  const urlPanel = params.get("panel");
  // Раздел может закрыть окно и на карточке объекта (`defaults.panelOpen: false`: журнал заказа уже на карточке).
  const cardOpen = fallbackOpen && section?.defaults?.panelOpen !== false;
  const panelOpen = urlPanel === "open" ? true : urlPanel === "closed" ? false : wide && cardOpen;

  const isStrictlyOverlay = Boolean(section?.path.startsWith("/chats"));
  // Поверх — в списках (таблица не сжимается). Где окно открыто вместе с работой — на карточке объекта и в разделах
  // с `defaults.panelMode: "docked"` (переписка) — закреплено рядом, иначе поверх оно закрыло бы кнопки самой карточки.
  // Выбор пользователя (булавка) важнее; закрепление действует на ≥ 1280 px (`canDock`), уже — всегда поверх.
  const defaultMode: PanelLayoutMode =
    fallbackOpen || section?.defaults?.panelMode === "docked" ? "docked" : "overlay";
  const panelMode: PanelLayoutMode = isStrictlyOverlay
    ? "overlay"
    : (entry?.panelMode ?? defaultMode);
  const isWideByDefault = Boolean(
    section?.path.startsWith("/erp/calc") ||
    section?.path.startsWith("/erp/docs") ||
    section?.path.startsWith("/eds"),
  );
  const panelWidth: PanelWidthPreset = entry?.panelWidth ?? (isWideByDefault ? "wide" : "default");

  const isDesktopWide =
    menuWide && (typeof window !== "undefined" ? window.innerWidth >= 1440 : true);
  const defaultMenuOpen = isDesktopWide ? (section?.defaults?.menuOpen ?? true) : false;
  const menuOpen = entry?.menuOpen ?? defaultMenuOpen;

  const urlTab = params.get("tab");
  const savedTab = entry?.lastTab ?? "";
  const tab =
    urlTab && tabs.includes(urlTab)
      ? urlTab
      : tabs.includes(savedTab)
        ? savedTab
        : (tabs[0] ?? "card");

  const setPanelOpen = useCallback(
    (open: boolean) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (open) {
            next.set("panel", "open");
          } else if (cardOpen) {
            next.set("panel", "closed");
          } else {
            next.delete("panel");
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams, cardOpen],
  );

  const setPanelMode = useCallback(
    (mode: PanelLayoutMode) => {
      if (isStrictlyOverlay && mode === "docked") return;
      patch(key, { panelMode: mode });
    },
    [patch, key, isStrictlyOverlay],
  );

  const setPanelWidth = useCallback(
    (width: PanelWidthPreset) => {
      patch(key, { panelWidth: width });
    },
    [patch, key],
  );

  const setTab = useCallback(
    (next: string) => {
      setParams(
        (prev) => {
          const copy = new URLSearchParams(prev);
          copy.set("tab", next);
          return copy;
        },
        { replace: true },
      );
      patch(key, { lastTab: next });
    },
    [setParams, patch, key],
  );

  const toggleMenu = useCallback(() => {
    patch(key, { menuOpen: !menuOpen });
  }, [patch, key, menuOpen]);
  const togglePanel = useCallback(() => {
    setPanelOpen(!panelOpen);
  }, [setPanelOpen, panelOpen]);

  return {
    menuOpen,
    panelOpen,
    panelMode,
    panelWidth,
    tab,
    tabs,
    toggleMenu,
    togglePanel,
    setPanelOpen,
    setPanelMode,
    setPanelWidth,
    setTab,
  };
}
