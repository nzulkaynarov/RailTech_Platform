import { describe, expect, it } from "vitest";

import { resources } from "../shared/i18n";
import { MODULES, matchSection } from "./registry";

const ru = resources.ru.modules;
type ModuleKey = "dashboard" | "crm" | "eds" | "erp" | "chats" | "admin";

function menuOf(code: ModuleKey): string[] {
  const module = MODULES.find((m) => m.code === code);
  const sections = ru[code].sections as Record<string, string>;
  return (module?.sections ?? []).filter((s) => !s.hidden).map((s) => sections[s.key] ?? "?");
}

describe("меню модулей дословно SPEC-v3 §6.2", () => {
  it("Dashboard", () => {
    expect(menuOf("dashboard")).toEqual(["Моя очередь", "Все проекты", "Сводка по компании"]);
  });
  it("CRM", () => {
    expect(menuOf("crm")).toEqual([
      "Все сообщения",
      "Все лиды",
      "Все клиенты",
      "Все заявки",
      "Каналы связи",
      "База знаний",
    ]);
  });
  it("EDS", () => {
    expect(menuOf("eds")).toEqual([
      "Все документы",
      "Входящие",
      "Исходящие",
      "Все проекты",
      "Черновик",
      "На согласовании",
      "Счета и оплаты",
    ]);
  });
  it("ERP", () => {
    expect(menuOf("erp")).toEqual([
      "Все запросы",
      "Расчёт",
      "Склад",
      "Справочники",
      "Документация",
    ]);
  });
  it("Chats", () => {
    expect(menuOf("chats")).toEqual(["Все чаты", "Внутренний", "Внешний", "Контакты"]);
  });
  it("Admin", () => {
    expect(menuOf("admin")).toEqual([
      "Ролевая матрица (RBAC)",
      "Оргструктура",
      "Внешние интеграции",
      "Журнал интеграций",
      "Тикеты от команды",
      "Компания",
    ]);
  });

  it("главные действия модулей — SPEC-v3 §6.2", () => {
    expect(ru.crm.action).toBe("Создать заявку");
    expect(ru.eds.action).toBe("Создать документ");
    expect(ru.erp.action).toBe("Создать запрос");
    expect(ru.chats.action).toBe("Создать чат");
    expect(ru.admin.action).toBe("Пригласить сотрудника");
    expect(MODULES.find((m) => m.code === "dashboard")?.action).toBeUndefined();
  });

  it("порядок и номера модулей", () => {
    expect(MODULES.map((m) => `${String(m.order)}. ${m.name}`)).toEqual([
      "1. Dashboard",
      "2. CRM",
      "3. EDS",
      "4. ERP",
      "5. Chats",
      "6. Admin",
    ]);
  });
});

describe("карта маршрутов SPEC-v3 §6.3", () => {
  const listPaths = [
    "/dashboard/queue",
    "/dashboard/projects",
    "/dashboard/summary",
    "/crm/messages",
    "/crm/leads",
    "/crm/clients",
    "/crm/requests",
    "/crm/channels",
    "/crm/kb",
    "/eds/documents",
    "/eds/inbox",
    "/eds/outbox",
    "/eds/projects",
    "/eds/drafts",
    "/eds/approvals",
    "/eds/payments",
    "/eds/new",
    "/erp/requests",
    "/erp/calc",
    "/erp/stock",
    "/erp/catalog",
    "/erp/docs",
    "/chats",
    "/chats/contacts",
    "/admin/roles",
    "/admin/org",
    "/admin/integrations",
    "/admin/tickets",
    "/admin/company",
  ];
  it.each(listPaths)("%s — есть раздел", (path) => {
    expect(matchSection(path)).toBeDefined();
  });

  const detailPaths = [
    "/crm/leads/L-2041",
    "/crm/clients/42",
    "/eds/inbox/%D0%92%D0%A5-104%2F26",
    "/eds/outbox/1",
    "/eds/projects/%D0%9F%D0%A0-2026-104",
    "/eds/drafts/1",
    "/eds/approvals/1",
    "/eds/payments/1",
    "/erp/requests/1",
    "/erp/calc/1",
    "/chats/1",
    "/admin/org/7",
  ];
  it.each(detailPaths)("%s — карточка объекта", (path) => {
    expect(matchSection(path)?.objectId).toBeDefined();
  });

  it("/chats/contacts — раздел, а не карточка чата", () => {
    const hit = matchSection("/chats/contacts");
    expect(hit?.section.key).toBe("contacts");
    expect(hit?.objectId).toBeUndefined();
  });

  it("?scope=internal|external выбирает пункт Chats, без параметра — «Все чаты»", () => {
    expect(matchSection("/chats", "?scope=internal")?.section.key).toBe("internal");
    expect(matchSection("/chats", "?scope=external")?.section.key).toBe("external");
    expect(matchSection("/chats", "")?.section.key).toBe("all");
    expect(matchSection("/chats", "?panel=open")?.section.key).toBe("all");
  });

  it("неизвестный адрес — нет раздела", () => {
    expect(matchSection("/crm/nothing")).toBeUndefined();
    expect(matchSection("/")).toBeUndefined();
  });

  it("пути и ключи разделов уникальны, у каждого есть тексты заглушки на трёх языках", () => {
    const seen = new Set<string>();
    for (const module of MODULES) {
      for (const section of module.sections) {
        const id = `${module.code}:${section.key}`;
        expect(seen.has(id), id).toBe(false);
        seen.add(id);
        for (const lng of ["ru", "uz", "en"] as const) {
          const stub = (
            resources[lng].modules[module.code].stub as Record<
              string,
              { title: string; text: string; action: string } | undefined
            >
          )[section.key];
          expect(stub?.title, `${lng} ${id}`).toBeTruthy();
          expect(stub?.text, `${lng} ${id}`).toBeTruthy();
          expect(stub?.action, `${lng} ${id}`).toBeTruthy();
        }
      }
    }
  });

  it("вкладки бокового окна: у каждой есть подпись и текст на трёх языках", () => {
    for (const module of MODULES) {
      for (const section of module.sections) {
        for (const tab of section.tabs ?? [
          { key: "card" },
          { key: "chat" },
          { key: "documents" },
        ]) {
          for (const lng of ["ru", "uz", "en"] as const) {
            const tabs = resources[lng].modules.tabs as Record<string, string>;
            const panel = resources[lng].modules.panel as Record<
              string,
              { title: string } | undefined
            >;
            expect(tabs[tab.key], `${lng} tab ${tab.key}`).toBeTruthy();
            expect(panel[tab.key]?.title, `${lng} panel ${tab.key}`).toBeTruthy();
          }
        }
      }
    }
  });
});

describe("Chats: ?scope= — фильтр списка, ?tab= — вкладка бокового окна", () => {
  it("?tab= не меняет выбранный пункт Chats", () => {
    expect(matchSection("/chats", "?scope=internal&tab=files")?.section.key).toBe("internal");
    expect(matchSection("/chats", "?tab=files")?.section.key).toBe("all");
  });
});
