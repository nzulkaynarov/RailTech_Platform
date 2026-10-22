import type { ModuleConfig } from "../types";

const CHATS_TABS = [{ key: "about" }, { key: "documents" }, { key: "files" }] as const;

/** Фильтр списка — `?scope=internal|external` (решение архитектора по Q-PLT-12-3: `?tab=` везде только вкладка бокового окна). */
export const chats: ModuleConfig = {
  code: "chats",
  order: 5,
  name: "Chats",
  action: { access: "chats.internal" },
  sections: [
    {
      key: "all",
      path: "/chats",
      detail: "/chats/:id",
      access: { anyOf: ["chats.internal", "chats.external"] },
      tabs: CHATS_TABS,
    },
    {
      key: "internal",
      path: "/chats?scope=internal",
      access: { resource: "chats.internal" },
      tabs: CHATS_TABS,
    },
    {
      key: "external",
      path: "/chats?scope=external",
      access: { resource: "chats.external" },
      tabs: CHATS_TABS,
      actionTo: "/chats?scope=internal",
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
