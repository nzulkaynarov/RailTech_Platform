import { createContext } from "react";

/**
 * Место вкладок раздела сразу под заголовком страницы. `PageHeader` объявляет его (`register`), оболочка кладёт туда
 * вкладки раздела (Товары · Склад · Документация, Счета · Заявки на оплату): вкладки больше не стоят над заголовком.
 * Страница без `PageHeader` не объявляет место — вкладки остаются на прежнем месте, над страницей.
 */
export interface PageTabsSlot {
  target: HTMLElement | null;
  register: (element: HTMLElement | null) => void;
}

export const PageTabsSlotContext = createContext<PageTabsSlot | null>(null);
