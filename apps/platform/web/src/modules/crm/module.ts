import type { ModuleConfig } from "../types";

export const crm: ModuleConfig = {
  code: "crm",
  sections: [
    {
      key: "messages",
      path: "/crm/messages",
      // Первая линия (`crm.leads.triage`, D17G-1) — разбор и «Передать менеджеру»
      access: { anyOf: ["crm.leads", "crm.leads.triage"] },
      actionTo: "/crm/leads",
    },
    {
      key: "leads",
      path: "/crm/leads",
      detail: "/crm/leads/:id",
      access: { anyOf: ["crm.leads", "crm.leads.triage"] },
      defaults: { panelOpen: false },
    },
    {
      key: "clients",
      path: "/crm/clients",
      detail: "/crm/clients/:id",
      // 0.3 (FR-13): снабженец без `crm.clients` видит здесь партнёров каталога (`erp.stock`), клиентов — нет.
      access: { anyOf: ["crm.clients", "erp.stock"] },
      actionTo: "/crm/leads",
    },
    { key: "requests", path: "/crm/requests", access: { resource: "crm.clients" } },
    { key: "channels", path: "/crm/channels", access: { resource: "crm.leads" } },
    // База знаний: читают лиды (`crm.leads`) и администратор (`admin`, он её ведёт — `kb:write`), W13-A5
    {
      key: "kb",
      path: "/crm/kb",
      access: { anyOf: ["crm.leads", "admin"] },
      // В подменю Клиентов — менеджеру; администратор входит из Настроек · Telegram-бот (W15-H4)
      menuAccess: { resource: "crm.leads" },
      defaults: { panelOpen: false },
    },
  ],
};
