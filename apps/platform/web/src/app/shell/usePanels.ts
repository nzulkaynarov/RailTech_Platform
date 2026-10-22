import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

import type { SectionConfig } from "../../modules/types";
import { DEFAULT_TABS } from "../../modules/types";
import { panelsKey, usePanelsStore } from "./panelsStore";
import { useViewport } from "./useViewport";

export interface Panels {
  menuOpen: boolean;
  panelOpen: boolean;
  tab: string;
  tabs: readonly string[];
  toggleMenu: () => void;
  togglePanel: () => void;
  setPanelOpen: (open: boolean) => void;
  setTab: (tab: string) => void;
}

/**
 * Подменю: запоминается на пользователя и раздел. Боковое окно: `?panel=` важнее сохранённого, дальше сохранённое,
 * дальше умолчание раздела. На экранах < 1200 боковое окно — Drawer поверх основного: по умолчанию закрыт, открывается
 * только явным `?panel=open` и не записывается в сохранённое состояние широкого экрана.
 */
export function usePanels(userId: string, section: SectionConfig | undefined): Panels {
  const { wide } = useViewport();
  const [params, setParams] = useSearchParams();
  const key = panelsKey(userId, section?.path.split("?")[0] ?? "-");
  const entry = usePanelsStore((s) => s.entries[key]);
  const patch = usePanelsStore((s) => s.patch);

  const tabs = useMemo(() => (section?.tabs ?? DEFAULT_TABS).map((t) => t.key), [section]);

  const urlPanel = params.get("panel");
  const panelOpen = wide
    ? urlPanel === "open"
      ? true
      : urlPanel === "closed"
        ? false
        : (entry?.panelOpen ?? section?.defaults?.panelOpen ?? true)
    : urlPanel === "open";
  const menuOpen = entry?.menuOpen ?? section?.defaults?.menuOpen ?? true;

  const urlTab = params.get("tab");
  const tab =
    urlTab && tabs.includes(urlTab)
      ? urlTab
      : tabs.includes(entry?.tab ?? "")
        ? (entry?.tab ?? "")
        : (tabs[0] ?? "card");

  const setPanelOpen = useCallback(
    (open: boolean) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("panel", open ? "open" : "closed");
          return next;
        },
        { replace: true },
      );
      if (wide) patch(key, { panelOpen: open });
    },
    [setParams, patch, key, wide],
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
      patch(key, { tab: next });
    },
    [setParams, patch, key],
  );

  return {
    menuOpen,
    panelOpen,
    tab,
    tabs,
    toggleMenu: () => {
      patch(key, { menuOpen: !menuOpen });
    },
    togglePanel: () => {
      setPanelOpen(!panelOpen);
    },
    setPanelOpen,
    setTab,
  };
}
