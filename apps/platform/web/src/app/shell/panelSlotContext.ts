import type { ModuleCode } from "../../shared/api/generated/model";
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
  /** Сколько форм сейчас открыто поверх карточки (`PanelPortal over`): пока есть хоть одна, окно открыто на «Карточке» */
  overs: number;
  claimOver: () => () => void;
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

/** Для каркаса: в окне открыта форма (`FormSheet`) — окно показывается независимо от адреса и выбора пользователя. */
export function usePanelForced(): boolean {
  return (useContext(PanelSlotContext)?.overs ?? 0) > 0;
}

/**
 * Нужна ли экрану кнопка окна: окно открывает форма поверх, его наполнил экран (занятая или встроенная вкладка) или у
 * раздела есть карточка объекта (`detail`). Форма без карточки и список без карточки в окне (справочники, «Люди»)
 * окна не имеют: пустое окно с «Объект не выбран» не открывается.
 */
export function panelAvailable(forced: boolean, hasContent: boolean, hasDetail: boolean): boolean {
  return forced || hasContent || hasDetail;
}

/** Для каркаса: какие вкладки сейчас заняты страницами (`PanelPortal`). */
export function usePanelClaims(): readonly string[] {
  return useContext(PanelSlotContext)?.claimed ?? [];
}

/**
 * Какие вкладки показать (ЕД-7: вкладка без данных не показывается, заглушек вроде «Чат не открыт» нет). Видна вкладка,
 * которую занял экран (`claimed`) или которую каркас наполняет сам (`builtIn`). Если не видна ни одна (список, где
 * окно ничем не занято), остаётся первая вкладка с её пояснением — окно не бывает без вкладок.
 */
export function visiblePanelTabs(
  tabs: readonly string[],
  claimed: readonly string[],
  builtIn: (tab: string) => boolean,
  forced = false,
): readonly string[] {
  // Форма поверх (`FormSheet layer="panel"`) живёт на «Карточке»: набор раздела её может не иметь — вкладка остаётся видимой.
  const withForm = forced && !tabs.includes(FORM_TAB) ? [FORM_TAB, ...tabs] : tabs;
  const shown = withForm.filter(
    (tab) => claimed.includes(tab) || builtIn(tab) || (forced && tab === FORM_TAB),
  );
  if (shown.length > 0) return shown;
  return tabs.slice(0, 1);
}

/** Экран ничего не положил в окно: ни занятых вкладок, ни тех, что наполняет каркас. */
export function panelHasContent(
  tabs: readonly string[],
  claimed: readonly string[],
  builtIn: (tab: string) => boolean,
): boolean {
  return tabs.some((tab) => claimed.includes(tab) || builtIn(tab));
}

/** Вкладка формы поверх: `panelForced` переводит каркас на неё. */
export const FORM_TAB = "card";

/** Активная вкладка среди видимых: выбранная пользователем, а если она исчезла (данные ушли) — первая видимая. */
export function effectivePanelTab(active: string, visible: readonly string[]): string {
  return visible.includes(active) ? active : (visible[0] ?? active);
}

/** Вкладки, которые наполняет сам каркас (лента «Сегодня» и уведомления в «Моей очереди»): они видны без страницы. */
export function hasBuiltInTab(
  module: ModuleCode | undefined,
  section: string | undefined,
  tab: string,
): boolean {
  return (
    module === "dashboard" && section === "queue" && (tab === "today" || tab === "notifications")
  );
}
