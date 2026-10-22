import type { ModuleConfig } from "../types";

export const admin: ModuleConfig = {
  code: "admin",
  order: 6,
  name: "Admin",
  action: { access: "admin" },
  sections: [
    {
      key: "roles",
      path: "/admin/roles",
      access: { resource: "admin" },
      tabs: [{ key: "role" }, { key: "employees" }, { key: "journal" }],
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
      key: "tickets",
      path: "/admin/tickets",
      access: { resource: "admin" },
      tabs: [{ key: "card" }],
      actionTo: "/admin/org",
    },
  ],
};
