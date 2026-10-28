import type { ModuleConfig } from "../types";

/** Вкладки бокового окна расчёта: «Задание» (резолюция, визы, чат проекта), чат и документы (SPEC-v3 §7.4). */
const CALC_TABS = [{ key: "task" }, { key: "chat" }, { key: "documents" }] as const;

export const erp: ModuleConfig = {
  code: "erp",
  action: { access: "erp.calc" },
  sections: [
    {
      key: "requests",
      path: "/erp/requests",
      detail: "/erp/requests/:id",
      access: { resource: "erp.calc" },
      tabs: CALC_TABS,
      // Таблица заявок на всю ширину; «Задание» открывается кликом по строке (SPEC-v3 §11.2 п. 4).
      defaults: { panelOpen: false },
      sheetOnMobile: true,
    },
    {
      key: "calc",
      path: "/erp/calc",
      detail: "/erp/calc/:id",
      access: { resource: "erp.calc" },
      tabs: CALC_TABS,
      defaults: { menuOpen: false },
      actionTo: "/erp/requests",
      sheetOnMobile: true,
    },
    {
      key: "stock",
      path: "/erp/stock",
      // Карточка заказа поставщику `/erp/stock/ЗП-…`; «Журнал» заказа — боковое окно (D2-2, SPEC-v3 §7.4).
      detail: "/erp/stock/:id",
      access: { resource: "erp.stock" },
      tabs: [{ key: "journal" }],
      defaults: { panelOpen: false },
      actionTo: "/erp/catalog",
    },
    {
      key: "catalog",
      path: "/erp/catalog",
      access: { resource: "erp.stock" },
      actionTo: "/erp/stock",
    },
    { key: "docs", path: "/erp/docs", access: { resource: "erp.stock" }, actionTo: "/erp/catalog" },
  ],
};
