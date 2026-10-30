import type { ModuleConfig } from "../types";

export const crm: ModuleConfig = {
  code: "crm",
  // «+ Создать заявку» — из лида или клиента (D1-2b): кнопка подменю ведёт к лидам, которые просят КП.
  action: { access: "crm.clients", to: "/crm/leads?status=wants_quote" },
  sections: [
    {
      key: "messages",
      path: "/crm/messages",
      access: { resource: "crm.leads" },
      actionTo: "/crm/leads",
      // карточка лида нужна рядом с перепиской: поверх она закрыла бы поле ответа и «Отправить»
      defaults: { panelMode: "docked" },
    },
    {
      key: "leads",
      path: "/crm/leads",
      detail: "/crm/leads/:id",
      access: { resource: "crm.leads" },
      defaults: { panelOpen: false },
    },
    {
      key: "clients",
      path: "/crm/clients",
      detail: "/crm/clients/:id",
      access: { resource: "crm.clients" },
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
      menuHome: { module: "admin", section: "bot" },
      defaults: { panelOpen: false },
    },
  ],
};
