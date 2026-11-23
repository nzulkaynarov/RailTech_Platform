import type { ModuleConfig } from "../types";

const CHATS_TABS = [{ key: "about" }, { key: "documents" }, { key: "files" }] as const;

/** Старые фильтры `?scope=internal|external` — `legacyRedirects.ts`. */
export const chats: ModuleConfig = {
  code: "chats",
  sections: [
    {
      key: "calendar",
      path: "/chats/calendar",
      access: { resource: "dashboard.queue" },
      hidden: true,
      defaults: { panelOpen: false },
    },
    {
      key: "all",
      path: "/chats",
      detail: "/chats/:id",
      access: { anyOf: ["chats.internal", "chats.external"] },
      tabs: CHATS_TABS,
    },
    {
      key: "contacts",
      path: "/chats/contacts",
      // Как в секции `menu` каталога: «Контакты» — по разделу внутреннего чата.
      access: { resource: "chats.internal" },
      tabs: CHATS_TABS,
    },
  ],
};
