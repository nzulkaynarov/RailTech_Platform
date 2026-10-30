import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

import type { SectionConfig } from "../../modules/types";
import { DEFAULT_TABS } from "../../modules/types";
import {
  USER_SCOPE,
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
 * Подменю: одно значение на пользователя (UX-1a): по умолчанию на ≥ 1440 px открыто, уже — свёрнуто; дальше — только
 * выбор пользователя (⌘\ или кнопка), переход между разделами его не меняет.
 * Боковое окно: открыто только по адресу — `?panel=open`; на карточке объекта (`:id`) на широком экране открыто,
 * пока не закрыто явно (`?panel=closed`).
 * Вид окна (режим overlay/docked, ширина default/wide, последняя вкладка lastTab) — по разделу в panelsStore
 * (localStorage ключ rt-pf-panels-v2). Режим по умолчанию — поверх везде; рядом — только выбор пользователя (булавка),
 * а поместится ли окно рядом, решает каркас (`AppShell`, рабочей области ≥ 760 px).
 */
export function usePanels(
  userId: string,
  section: SectionConfig | undefined,
  fallbackOpen = false,
): Panels {
  const { wide, menuWide } = useViewport();
  const [params, setParams] = useSearchParams();
  const key = panelsKey(userId, section?.path.split("?")[0] ?? "-");
  const userKey = panelsKey(userId, USER_SCOPE);
  const entry = usePanelsStore((s) => s.entries[key]);
  const storedMenuOpen = usePanelsStore((s) => s.entries[userKey]?.menuOpen);
  const patch = usePanelsStore((s) => s.patch);

  const tabs = useMemo(() => (section?.tabs ?? DEFAULT_TABS).map((t) => t.key), [section]);

  // Открытие панели: в списках определяется ?panel=open в URL; на карточке объекта (:id) — fallbackOpen на широком экране
  const urlPanel = params.get("panel");
  // Раздел может закрыть окно и на карточке объекта (`defaults.panelOpen: false`: журнал заказа уже на карточке).
  const cardOpen = fallbackOpen && section?.defaults?.panelOpen !== false;
  const panelOpen = urlPanel === "open" ? true : urlPanel === "closed" ? false : wide && cardOpen;

  const isStrictlyOverlay = Boolean(section?.path.startsWith("/chats"));
  // Поверх — везде по умолчанию (решение владельца 2026-10-30, п. 2): таблицы и карточки не сжимаются. Рядом — только
  // булавкой пользователя; закрепление действует на ≥ 1280 px и при рабочей области ≥ 760 px (AppShell), иначе — поверх.
  const panelMode: PanelLayoutMode = isStrictlyOverlay
    ? "overlay"
    : (entry?.panelMode ?? "overlay");
  // 600 px — только выбор пользователя («Шире»), не умолчание раздела.
  const panelWidth: PanelWidthPreset = entry?.panelWidth ?? "default";

  const menuOpen = storedMenuOpen ?? menuWide;

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
    patch(userKey, { menuOpen: !menuOpen });
  }, [patch, userKey, menuOpen]);
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
