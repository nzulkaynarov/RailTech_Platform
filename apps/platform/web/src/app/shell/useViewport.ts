import { useSyncExternalStore } from "react";

/** Границы адаптивности каркаса (docs/architecture/platform-frontend.md §4): < 1440 — подменю свёрнуто по умолчанию, < 1280 — только overlay, < 1200 — боковое окно Drawer, < 768 — нижняя панель. */
export const MENU_WIDE_QUERY = "(min-width: 1440px)";
export const WIDE_QUERY = "(min-width: 1200px)";
export const DOCK_QUERY = "(min-width: 1280px)";
export const TABLET_QUERY = "(min-width: 768px)";

function makeMedia(query: string): () => boolean {
  const subscribe = (notify: () => void) => {
    const list = window.matchMedia(query);
    list.addEventListener("change", notify);
    return () => {
      list.removeEventListener("change", notify);
    };
  };
  const snapshot = () => window.matchMedia(query).matches;
  // SSR нет; на сервере считаем экран широким.
  return () => useSyncExternalStore(subscribe, snapshot, () => true);
}

const useMenuWide = makeMedia(MENU_WIDE_QUERY);
const useWide = makeMedia(WIDE_QUERY);
const useDock = makeMedia(DOCK_QUERY);
const useTablet = makeMedia(TABLET_QUERY);

export interface Viewport {
  /** ≥ 1440: подменю ModuleMenu развёрнуто по умолчанию */
  menuWide: boolean;
  /** ≥ 1200: боковое окно может быть открыто на детальной карточке */
  wide: boolean;
  /** ≥ 1280: доступно закрепление в сетке (Docked) */
  canDock: boolean;
  /** < 768: рейл — нижняя панель, подменю — Drawer */
  mobile: boolean;
}

export function useViewport(): Viewport {
  const menuWide = useMenuWide();
  const wide = useWide();
  const canDock = useDock();
  const tablet = useTablet();
  return { menuWide, wide, canDock, mobile: !tablet };
}
