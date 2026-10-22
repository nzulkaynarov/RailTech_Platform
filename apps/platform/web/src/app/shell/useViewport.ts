import { useSyncExternalStore } from "react";

/** Границы адаптивности каркаса (03-frontend.md §4): < 1200 — боковое окно Drawer, < 768 — нижняя панель. */
export const WIDE_QUERY = "(min-width: 1200px)";
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

const useWide = makeMedia(WIDE_QUERY);
const useTablet = makeMedia(TABLET_QUERY);

export interface Viewport {
  /** ≥ 1200: боковое окно — колонка справа */
  wide: boolean;
  /** < 768: рейл — нижняя панель, подменю — Drawer */
  mobile: boolean;
}

export function useViewport(): Viewport {
  const wide = useWide();
  const tablet = useTablet();
  return { wide, mobile: !tablet };
}
