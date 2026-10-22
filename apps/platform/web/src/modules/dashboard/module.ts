import type { ModuleConfig } from "../types";

export const dashboard: ModuleConfig = {
  code: "dashboard",
  order: 1,
  name: "Dashboard",
  sections: [
    {
      key: "queue",
      path: "/dashboard/queue",
      access: { resource: "dashboard.queue" },
      tabs: [{ key: "today" }, { key: "notifications" }],
      actionTo: "/dashboard/projects",
    },
    {
      key: "projects",
      path: "/dashboard/projects",
      access: { resource: "eds.projects" },
      actionTo: "/dashboard/queue",
    },
    {
      key: "summary",
      path: "/dashboard/summary",
      access: { resource: "dashboard.summary" },
      actionTo: "/dashboard/queue",
    },
  ],
};
