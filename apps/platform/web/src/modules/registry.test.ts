import { describe, expect, it } from "vitest";

import { resources } from "../shared/i18n";
import { findNavItem, NAVIGATION } from "./navigation";
import { MODULES, matchSection } from "./registry";

const ru = resources.ru.modules;
type ModuleKey = "dashboard" | "crm" | "eds" | "erp" | "chats" | "admin";

function menuOf(code: ModuleKey): string[] {
  const labels = ru[code].nav as Record<string, string>;
  return NAVIGATION[code].map((item) => labels[item.key] ?? "?");
}

describe("меню — docs/product/NAVIGATION.md", () => {
  it("пункты модулей", () => {
    expect(menuOf("dashboard")).toEqual(["Задачи", "Проекты", "Сводка"]);
    expect(menuOf("crm")).toEqual(["Лиды", "Контрагенты", "Почта", "База знаний"]);
    expect(menuOf("eds")).toEqual(["Входящие", "Исходящие", "Внутренние", "Архив", "Шаблоны"]);
    expect(menuOf("erp")).toEqual(["Заявки", "Каталог", "Финансы"]);
    expect(menuOf("chats")).toEqual(["Календарь", "Чаты", "Люди"]);
    expect(menuOf("admin")).toEqual(["Сотрудники", "Компания", "Подключения", "Журнал"]);
    expect(MODULES.flatMap((m) => menuOf(m.code))).toHaveLength(22);
  });

  it("у каждого раздела из меню есть конфигурация", () => {
    const refs = MODULES.flatMap((m) =>
      NAVIGATION[m.code].flatMap((item) => [
        ...item.targets.map((t) => t.section),
        ...(item.also ?? []),
      ]),
    );
    const known = MODULES.flatMap((m) => m.sections.map((s) => `${m.code}.${s.key}`));
    for (const ref of refs) expect(known, ref).toContain(ref);
  });

  it("адрес находит свой пункт меню", () => {
    const at = (url: string) => {
      const [pathname = "", query = ""] = url.split("?");
      const search = query ? `?${query}` : "";
      const match = matchSection(pathname, search);
      const hit = match ? findNavItem(match, pathname, search) : undefined;
      return hit ? [hit.module, hit.item.key, hit.tab?.key].filter(Boolean).join(".") : undefined;
    };
    expect(at("/eds/documents?box=archive")).toBe("eds.archive");
    expect(at("/eds/documents?box=internal")).toBe("eds.internal");
    expect(at("/eds/documents")).toBeUndefined();
    expect(at("/eds/payments")).toBe("erp.finance.invoices");
    expect(at("/eds/payments?show=memos")).toBe("erp.finance.memos");
    expect(at("/eds/projects")).toBe("dashboard.projects");
    expect(at("/admin/org")).toBe("admin.people.org");
    // индекс группы — страница «Все настройки», пункты меню ведут на сами страницы
    expect(at("/admin?group=channels")).toBeUndefined();
    expect(at("/admin/telegram")).toBe("admin.channels.telegram");
    expect(at("/admin/templates")).toBe("eds.templates");
    expect(at("/erp/stock")).toBe("erp.catalog.stock");
    expect(at("/erp/stock?view=orders")).toBe("erp.requests.purchases");
    expect(at("/erp/calc")).toBe("erp.requests.sales");
    expect(at("/crm/messages")).toBe("crm.leads");
  });
});

describe("имена модулей — UX-оценка 2026-10-27 §6.1", () => {
  const names = (lng: "ru" | "uz" | "en", field: "name" | "title") =>
    MODULES.map((m) => resources[lng].modules[m.code][field]);

  it("порядок рейла и имена в рейле на трёх языках", () => {
    expect(MODULES.map((m) => m.code)).toEqual([
      "dashboard",
      "crm",
      "eds",
      "erp",
      "chats",
      "admin",
    ]);
    expect(names("ru", "name")).toEqual([
      "Главная",
      "Контакты",
      "Документы",
      "Операции",
      "Органайзер",
      "Настройки",
    ]);
    expect(names("uz", "name")).toEqual([
      "Asosiy",
      "Kontaktlar",
      "Hujjatlar",
      "Amallar",
      "Organayzer",
      "Sozlamalar",
    ]);
    expect(names("en", "name")).toEqual([
      "Home",
      "Contacts",
      "Documents",
      "Operations",
      "Organizer",
      "Settings",
    ]);
  });

  it("заголовок подменю — полное имя модуля", () => {
    expect(names("ru", "title")).toEqual([
      "Главная",
      "Контакты",
      "Документы",
      "Операции",
      "Органайзер",
      "Настройки",
    ]);
  });

  it.each(["ru", "uz", "en"] as const)(
    "%s: в рейле не длиннее 10 символов, без номеров и внутренних кодов систем",
    (lng) => {
      for (const name of names(lng, "name")) expect(name.length, name).toBeLessThanOrEqual(10);
      for (const name of [...names(lng, "name"), ...names(lng, "title")]) {
        expect(name, name).not.toMatch(/^\d|\b(Dashboard|CRM|EDS|ERP|Admin|RBAC)\b/);
      }
    },
  );

  it.each(["ru", "uz"] as const)("%s: пункты подменю без английских имён систем", (lng) => {
    for (const module of MODULES) {
      const sections = resources[lng].modules[module.code].sections as Record<string, string>;
      for (const label of Object.values(sections)) {
        expect(label, label).not.toMatch(/\b(Dashboard|CRM|EDS|ERP|Chats|Admin|RBAC)\b/);
      }
    }
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
    "/admin",
    "/admin/articles",
    "/admin/company",
    "/admin/numbering",
    "/admin/taxes",
    "/admin/telegram",
    "/admin/mail",
    "/admin/web-forms",
    "/admin/dictionaries",
    "/admin/resolutions",
    "/admin/templates",
    "/admin/timing",
    "/admin/notifications",
    "/admin/ai-spend",
    "/admin/audit",
    "/admin/exports",
    "/admin/bus",
    "/admin/setup",
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

  it.each([
    ["/eds/inbox/ВХ-104/26", "inbox", "ВХ-104/26"],
    ["/eds/drafts/КП-2026/118", "drafts", "КП-2026/118"],
    ["/eds/approvals/СЗ-2026/031", "approvals", "СЗ-2026/031"],
  ])("%s — номер со «/» без кодирования — одна карточка", (path, section, number) => {
    const hit = matchSection(path);
    expect(hit?.section.key).toBe(section);
    expect(hit?.objectId).toBe(number);
  });

  it("лишние сегменты после карточки — не карточка", () => {
    expect(matchSection("/eds/inbox/ВХ-104/26/лишнее")).toBeUndefined();
    expect(matchSection("/eds/inbox/abc/def")).toBeUndefined();
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

  it("ключи разделов уникальны", () => {
    const seen = new Set<string>();
    for (const module of MODULES) {
      for (const section of module.sections) {
        const id = `${module.code}:${section.key}`;
        expect(seen.has(id), id).toBe(false);
        seen.add(id);
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
