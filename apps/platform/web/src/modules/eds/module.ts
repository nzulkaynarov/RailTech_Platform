import type { ModuleConfig } from "../types";

const EDS_ANY = [
  "eds.inbox",
  "eds.inbox.register",
  "eds.drafts",
  "eds.projects",
  "eds.payments",
  "eds.memo.create",
  "eds.memo.approve",
] as const;

export const eds: ModuleConfig = {
  code: "eds",
  action: { access: "eds.memo.create", to: "/eds/new" },
  sections: [
    {
      key: "documents",
      path: "/eds/documents",
      access: { anyOf: EDS_ANY },
      defaults: { panelOpen: false },
    },
    {
      key: "inbox",
      path: "/eds/inbox",
      detail: "/eds/inbox/:id",
      access: { anyOf: ["eds.inbox", "eds.inbox.register"] },
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
      // D2-5: договор и акт — вкладки бокового окна карточки проекта (SPEC-v3 §7.3); «Оплата» подключит D2-4.
      tabs: [{ key: "contract" }, { key: "act" }, { key: "journal" }, { key: "chat" }],
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
      // P8: «Зарегистрировать входящее» (SPEC-v3 §3.2a п. 1) — кнопка во «Входящих письмах»; регистрация ≠ резолюция.
      key: "register",
      path: "/eds/register",
      access: { resource: "eds.inbox.register", level: "full" },
      hidden: true,
      parent: "inbox",
      defaults: { panelOpen: false },
      actionTo: "/eds/inbox",
    },
    {
      // P8b: рабочий экран поручения по входящему (SPEC-v3 §3.2a п. 3–4) — из «Моих задач»; исполнитель — любой сотрудник,
      // письмо своего поручения он видит и без «Входящих» (решает EDS).
      key: "tasks",
      path: "/eds/tasks",
      detail: "/eds/tasks/:id",
      access: { resource: "dashboard.queue" },
      hidden: true,
      defaults: { panelOpen: false },
      actionTo: "/dashboard/queue",
    },
    {
      key: "new",
      path: "/eds/new",
      access: { resource: "eds.memo.create" },
      hidden: true,
      defaults: { panelOpen: false },
      actionTo: "/eds/documents",
    },
  ],
};
