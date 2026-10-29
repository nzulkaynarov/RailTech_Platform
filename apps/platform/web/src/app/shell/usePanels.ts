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
 * Боковое окно: открытие panelOpen определяется ТОЛЬКО наличием ?panel=open в URL.
 * Настройки отображения (режим overlay/docked, ширина default/wide, последняя вкладка lastTab)
 * сохраняются в panelsStore (localStorage ключ rt-pf-panels-v2).
 */
export function usePanels(
  userId: string,
  section: SectionConfig | undefined,
  fallbackOpen = false,
): Panels {
  const { wide } = useViewport();
  const [params, setParams] = useSearchParams();
  const key = panelsKey(userId, section?.path.split("?")[0] ?? "-");
  const entry = usePanelsStore((s) => s.entries[key]);
  const patch = usePanelsStore((s) => s.patch);

  const tabs = useMemo(() => (section?.tabs ?? DEFAULT_TABS).map((t) => t.key), [section]);

  // Открытие панели: в списках определяется ?panel=open в URL; на карточке объекта (:id) — fallbackOpen на широком экране
  const urlPanel = params.get("panel");
  const panelOpen =
    urlPanel === "open" ? true : urlPanel === "closed" ? false : wide && fallbackOpen;

  const panelMode: PanelLayoutMode = entry?.panelMode ?? "overlay";
  const panelWidth: PanelWidthPreset = entry?.panelWidth ?? "default";

  const isDesktopWide = typeof window !== "undefined" ? window.innerWidth >= 1440 : true;
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
          } else if (fallbackOpen) {
            next.set("panel", "closed");
          } else {
            next.delete("panel");
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams, fallbackOpen],
  );

  const setPanelMode = useCallback(
    (mode: PanelLayoutMode) => {
      patch(key, { panelMode: mode });
    },
    [patch, key],
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

  return {
    menuOpen,
    panelOpen,
    panelMode,
    panelWidth,
    tab,
    tabs,
    toggleMenu: () => {
      patch(key, { menuOpen: !menuOpen });
    },
    togglePanel: () => {
      setPanelOpen(!panelOpen);
    },
    setPanelOpen,
    setPanelMode,
    setPanelWidth,
    setTab,
  };
}
