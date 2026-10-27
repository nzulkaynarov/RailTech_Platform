import type { ModuleConfig } from "../types";

export const admin: ModuleConfig = {
  code: "admin",
  action: { access: "admin", to: "/admin/org?invite=open&panel=open" },
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
      detail: "/admin/tickets/:id",
      access: { resource: "admin" },
      tabs: [{ key: "card" }],
      actionTo: "/admin/org",
    },
    {
      // «Первый запуск» (W13-A4): мастер и чек-лист, открывается баннером; в подменю SPEC-v3 §6.2 его нет.
      key: "setup",
      path: "/admin/setup",
      access: { resource: "admin" },
      hidden: true,
      tabs: [{ key: "card" }],
      actionTo: "/admin/org",
    },
    {
      key: "company",
      path: "/admin/company",
      access: { resource: "company.settings" },
      tabs: [{ key: "card" }],
      // Настройки занимают всё основное окно; сводка по компании открывается по кнопке бокового окна.
      defaults: { panelOpen: false },
      actionTo: "/admin/org",
    },
    {
      key: "bot",
      path: "/admin/bot",
      access: { resource: "admin" },
      tabs: [{ key: "card" }],
      defaults: { panelOpen: false },
      actionTo: "/admin/org",
    },
    {
      key: "audit",
      path: "/admin/audit",
      access: { resource: "admin" },
      tabs: [{ key: "card" }],
      actionTo: "/admin/org",
    },
  ],
};
