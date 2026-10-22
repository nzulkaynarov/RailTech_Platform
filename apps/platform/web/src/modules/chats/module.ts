import type { ModuleConfig } from "../types";

const CHATS_TABS = [{ key: "about" }, { key: "documents" }, { key: "files" }] as const;

/** `?tab=internal|external` — фильтр списка (SPEC-v3 §6.3), поэтому вкладка бокового окна живёт в `?ptab=`. */
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
      tabParam: "ptab",
    },
    {
      key: "internal",
      path: "/chats?tab=internal",
      access: { resource: "chats.internal" },
      tabs: CHATS_TABS,
      tabParam: "ptab",
    },
    {
      key: "external",
      path: "/chats?tab=external",
      access: { resource: "chats.external" },
      tabs: CHATS_TABS,
      tabParam: "ptab",
      actionTo: "/chats?tab=internal",
    },
    {
      key: "contacts",
      path: "/chats/contacts",
      access: { anyOf: ["chats.internal", "chats.external"] },
      tabs: CHATS_TABS,
      tabParam: "ptab",
    },
  ],
};
