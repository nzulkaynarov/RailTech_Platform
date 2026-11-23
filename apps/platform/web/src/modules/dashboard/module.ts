import type { ModuleConfig } from "../types";

export const dashboard: ModuleConfig = {
  code: "dashboard",
  sections: [
    {
      key: "queue",
      path: "/dashboard/queue",
      access: { resource: "dashboard.queue" },
      tabs: [{ key: "today" }, { key: "notifications" }],
      actionTo: "/eds/projects",
    },
    {
      key: "summary",
      path: "/dashboard/summary",
      access: { resource: "dashboard.summary" },
      actionTo: "/dashboard/queue",
    },
  ],
};
