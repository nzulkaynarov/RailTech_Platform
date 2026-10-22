import type { ModuleConfig } from "../types";

export const erp: ModuleConfig = {
  code: "erp",
  order: 4,
  name: "ERP",
  action: { access: "erp.calc" },
  sections: [
    {
      key: "requests",
      path: "/erp/requests",
      detail: "/erp/requests/:id",
      access: { resource: "erp.calc" },
    },
    {
      key: "calc",
      path: "/erp/calc",
      detail: "/erp/calc/:id",
      access: { resource: "erp.calc" },
      tabs: [{ key: "task" }, { key: "chat" }, { key: "documents" }],
      defaults: { menuOpen: false },
      actionTo: "/erp/requests",
    },
    {
      key: "stock",
      path: "/erp/stock",
      access: { resource: "erp.stock" },
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
