import type { ModuleConfig } from "../types";

export const admin: ModuleConfig = {
  code: "admin",
  order: 6,
  name: "Admin",
  action: { access: "admin", to: "/admin/org?invite=open&panel=open" },
  sections: [
    {
      key: "roles",
      path: "/admin/roles",
      access: { resource: "admin" },
      tabs: [{ key: "role" }, { key: "employees" }],
      actionTo: "/admin/org",
    },
    {
      key: "org",
      path: "/admin/org",
      detail: "/admin/org/:userId",
      access: { resource: "admin" },
      tabs: [{ key: "card" }],
    },
    {
      key: "integrations",
      path: "/admin/integrations",
      access: { resource: "admin" },
      tabs: [{ key: "card" }],
      actionTo: "/admin/tickets",
    },
    {
      // Журнал интеграций (W13-A2): шина CRM, ERP и EDS — только `admin: full` (BFF читает тоже по full).
      key: "bus",
      path: "/admin/bus",
      access: { resource: "admin", level: "full" },
      tabs: [{ key: "card" }],
      actionTo: "/admin/integrations",
    },
    {
      key: "tickets",
      path: "/admin/tickets",
      access: { resource: "admin" },
      tabs: [{ key: "card" }],
      actionTo: "/admin/org",
    },
    {
      key: "company",
      path: "/admin/company",
      access: { resource: "company.settings" },
      tabs: [{ key: "card" }],
      actionTo: "/admin/org",
    },
  ],
};
