import type { ModuleConfig } from "../types";

/**
 * Настройки (admin). Порядок подменю — UX-оценка 2026-10-27 §6.2; W15-H4: один «Журнал» (действия людей и обмен между
 * системами — фильтр одного экрана), «Первый запуск» — в меню до завершения шагов, боковое окно закрыто там, где
 * выбирать нечего (обзор подключений, журнал без выбранной записи, мастер, бот, компания, обращения).
 */
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
      defaults: { panelOpen: false },
      actionTo: "/admin/tickets",
    },
    {
      key: "tickets",
      path: "/admin/tickets",
      detail: "/admin/tickets/:id",
      access: { resource: "admin" },
      tabs: [{ key: "card" }],
      defaults: { panelOpen: false },
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
      // Telegram-бот в одном месте (W15-H4): подключение, тексты, поведение, база знаний, шаблоны ответов, выгрузки.
      key: "bot",
      path: "/admin/bot",
      access: { resource: "admin" },
      tabs: [{ key: "card" }],
      defaults: { panelOpen: false },
      actionTo: "/admin/org",
    },
    {
      // «Журнал» (W15-H4): фильтр «Действия людей» — журнал аудита CRM.
      key: "audit",
      path: "/admin/audit",
      access: { resource: "admin" },
      tabs: [{ key: "card" }],
      defaults: { panelOpen: false },
      actionTo: "/admin/org",
    },
    {
      // Фильтр «Обмен между системами» того же «Журнала»: шина CRM, ERP и EDS — только `admin: full` (BFF читает тоже по full).
      key: "bus",
      path: "/admin/bus",
      access: { resource: "admin", level: "full" },
      hidden: true,
      parent: "audit",
      tabs: [{ key: "card" }],
      defaults: { panelOpen: false },
      actionTo: "/admin/integrations",
    },
    {
      // «Первый запуск» (W13-A4): мастер; в подменю — пока шаги не завершены (W15-H4).
      key: "setup",
      path: "/admin/setup",
      access: { resource: "admin" },
      showWhile: "setupPending",
      tabs: [{ key: "step" }],
      defaults: { panelOpen: false },
      actionTo: "/admin/org",
    },
  ],
};
