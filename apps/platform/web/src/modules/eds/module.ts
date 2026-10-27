import type { ModuleConfig } from "../types";

const EDS_ANY = [
  "eds.inbox",
  "eds.drafts",
  "eds.projects",
  "eds.payments",
  "eds.memo.create",
  "eds.memo.approve",
] as const;

export const eds: ModuleConfig = {
  code: "eds",
  action: { access: "eds.memo.create" },
  sections: [
    { key: "documents", path: "/eds/documents", access: { anyOf: EDS_ANY } },
    {
      key: "inbox",
      path: "/eds/inbox",
      detail: "/eds/inbox/:id",
      access: { resource: "eds.inbox" },
      tabs: [{ key: "resolution" }, { key: "chat" }, { key: "documents" }],
      actionTo: "/eds/documents",
    },
    {
      key: "outbox",
      path: "/eds/outbox",
      detail: "/eds/outbox/:id",
      access: { resource: "eds.drafts" },
      actionTo: "/eds/documents",
    },
    {
      key: "projects",
      path: "/eds/projects",
      detail: "/eds/projects/:id",
      access: { resource: "eds.projects" },
      actionTo: "/eds/documents",
    },
    {
      key: "drafts",
      path: "/eds/drafts",
      detail: "/eds/drafts/:id",
      access: { resource: "eds.drafts" },
      tabs: [{ key: "approve" }, { key: "chat" }, { key: "documents" }],
      actionTo: "/eds/documents",
    },
    {
      key: "approvals",
      path: "/eds/approvals",
      detail: "/eds/approvals/:id",
      access: { anyOf: ["eds.memo.approve", "eds.memo.create"] },
      tabs: [{ key: "agree" }, { key: "chat" }, { key: "documents" }],
    },
    {
      key: "payments",
      path: "/eds/payments",
      detail: "/eds/payments/:id",
      access: { resource: "eds.payments" },
      tabs: [{ key: "payment" }, { key: "chat" }, { key: "documents" }],
      actionTo: "/eds/projects",
    },
    {
      key: "new",
      path: "/eds/new",
      access: { resource: "eds.memo.create" },
      hidden: true,
      actionTo: "/eds/documents",
    },
  ],
};
