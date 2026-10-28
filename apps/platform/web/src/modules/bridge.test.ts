import { describe, expect, it } from "vitest";

import { RESOURCES } from "../app/rbac.generated";
import { resources } from "../shared/i18n";
import {
  BRIDGE,
  NATIVE_SECTIONS,
  bridgeEntry,
  isActionable,
  legacyHref,
  objectIdOf,
  routeTarget,
} from "./bridge";
import { MODULES } from "./registry";

const sectionIds = MODULES.flatMap((m) => m.sections.map((s) => `${m.code}.${s.key}`));

describe("мост в старые экраны: карта разделов-заглушек", () => {
  it("у каждого раздела — либо запись моста, либо настоящий экран (NATIVE_SECTIONS), не оба сразу", () => {
    for (const id of sectionIds) {
      const stub = id in BRIDGE;
      const native = NATIVE_SECTIONS.includes(id);
      expect(stub || native, `${id}: нет ни моста, ни настоящего экрана`).toBe(true);
      expect(stub && native, `${id}: и мост, и настоящий экран`).toBe(false);
    }
  });

  it("в карте нет разделов, которых нет в модулях", () => {
    for (const id of [...Object.keys(BRIDGE), ...NATIVE_SECTIONS]) {
      expect(sectionIds, id).toContain(id);
    }
  });

  it("запись говорит, где делается работа: старая система, другой раздел или кто делает вне интерфейса", () => {
    for (const [id, entry] of Object.entries(BRIDGE)) {
      expect(Boolean(entry.legacy || entry.who || entry.internal), id).toBe(true);
      expect(["soon", "pilot"], id).toContain(entry.when);
    }
  });

  it("старый экран с нужным разделом (B-D18-1): раздел есть в каталоге, и без него есть текст «кто делает»", () => {
    const needing = Object.entries(BRIDGE).filter(([, entry]) => entry.legacyNeeds !== undefined);
    expect(needing.map(([id]) => id)).toEqual(["chats.external"]);
    for (const [id, entry] of needing) {
      expect(Object.keys(RESOURCES), id).toContain(entry.legacyNeeds);
      expect(entry.legacy, id).toBeDefined();
      expect(entry.who, id).toBeDefined();
    }
  });

  it("волна 16 — «в ближайшем обновлении», остальное — «к пилоту»", () => {
    const soon = Object.entries(BRIDGE)
      .filter(([, entry]) => entry.when === "soon")
      .map(([id]) => id)
      .sort();
    expect(soon).toEqual([]);
  });

  it.each(["ru", "uz", "en"] as const)("%s: тексты есть для каждой записи", (lng) => {
    const bridge = resources[lng].bridge;
    for (const [id, entry] of Object.entries(BRIDGE)) {
      if (entry.legacy) {
        const where = (bridge.where as Record<string, string>)[entry.legacy.where];
        expect(where, `${lng} ${id} where.${entry.legacy.where}`).toBeTruthy();
      }
      if (entry.who) {
        const who = (bridge.who as Record<string, string>)[entry.who];
        expect(who, `${lng} ${id} who.${entry.who}`).toBeTruthy();
      }
    }
  });

  it.each(["ru", "uz", "en"] as const)(
    "%s: ни «пока нет», ни «фаза Pn» в текстах моста и системы",
    (lng) => {
      const text = JSON.stringify([resources[lng].bridge, resources[lng].shell.soon]);
      expect(text).not.toMatch(/пока нет|фаз[аеы] P\d|phase P\d|bosqich/i);
    },
  );

  it("пути моста совпадают с реальными маршрутами старых фронтов (роутер CRM, pageRegistry ERP)", () => {
    const crmRoutes = ["/inbox", "/leads", "/clients", "/dashboard"];
    // Хэш-маршруты `config/pageRegistry.ts` старого ERP.
    const erpRoutes = [
      "#crm-deals",
      "#crm-quotes",
      "#payments",
      "#my-products",
      "#catalog-reference",
      "#company-files",
    ];
    for (const [id, entry] of Object.entries(BRIDGE)) {
      const legacy = entry.legacy;
      if (!legacy) continue;
      const known = legacy.system === "crm" ? crmRoutes : erpRoutes;
      expect(known, `${id}: ${legacy.path}`).toContain(legacy.path);
    }
  });
});

describe("адрес кнопки", () => {
  const inbox = bridgeEntry("chats", "external")?.legacy;
  const deals = bridgeEntry("crm", "requests")?.legacy;

  it("старая CRM — путь к адресу, ERP — хэш-маршрут после слэша", () => {
    expect(inbox && legacyHref(inbox, "http://crm.localhost:8088")).toBe(
      "http://crm.localhost:8088/inbox",
    );
    expect(deals && legacyHref(deals, "http://erp.localhost:8088")).toBe(
      "http://erp.localhost:8088/#crm-deals",
    );
  });

  it("раздел без карточки объекта в старой системе — список и для номера", () => {
    expect(inbox && legacyHref(inbox, "http://crm.localhost", "L-2041")).toBe(
      "http://crm.localhost/inbox",
    );
  });

  it("«Лиды» и «Клиенты» — настоящие экраны (D1-2b): записей моста нет", () => {
    expect(bridgeEntry("crm", "leads")).toBeUndefined();
    expect(bridgeEntry("crm", "clients")).toBeUndefined();
  });

  it("числовой номер заявки — карточка сделки старого ERP, бизнес-номер — список сделок", () => {
    expect(deals && legacyHref(deals, "http://erp.localhost", "7")).toBe(
      "http://erp.localhost/#request-detail/7",
    );
    expect(deals && legacyHref(deals, "http://erp.localhost", "ЗВ-2026-104")).toBe(
      "http://erp.localhost/#crm-deals",
    );
  });

  it("адреса нет — кнопки нет", () => {
    expect(inbox && legacyHref(inbox, null)).toBeUndefined();
    expect(inbox && legacyHref(inbox, "")).toBeUndefined();
  });
});

describe("номер объекта из адреса", () => {
  it("карточка — :id, список — ?lead= / ?request=, иначе нет объекта", () => {
    expect(objectIdOf({ objectId: "ВХ-104/26" }, "")).toBe("ВХ-104/26");
    expect(objectIdOf({}, "?lead=L-2041&panel=open")).toBe("L-2041");
    expect(objectIdOf({}, "?request=ЗВ-2026-104")).toBe("ЗВ-2026-104");
    expect(objectIdOf({}, "?panel=open")).toBeUndefined();
  });
});

describe("исполнимость адреса: есть ли экран в Платформе (одна функция на задачи, поиск и колокольчик)", () => {
  it.each([
    ["/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution", true],
    ["/eds/inbox?letter=%D0%92%D0%A5-104%2F26", true],
    ["/dashboard/queue?panel=open&tab=notifications", true],
    ["/admin/org?invite=open&panel=open", true],
    ["/crm/leads?lead=L-2041&panel=open&tab=card", true],
    ["/crm/clients/17?panel=open&tab=card", true],
    ["/eds/drafts/%D0%9A%D0%9F-2026%2F118?panel=open&tab=approve", true],
    ["/eds/approvals/%D0%A1%D0%97-2026%2F031?panel=open&tab=agree", true],
    ["/crm/messages?lead=L-2041", true],
    ["/eds/documents?doc=5f0c7a52-3b1e-4c53-9d0a-1c6a1f0e2b77", true],
    ["/eds/new?type=memo", true],
    ["/eds/payments/%D0%A1%D0%A7-2026%2F142", true],
    ["/erp/calc", true],
    ["/erp/stock", true],
    ["/erp/stock/%D0%97%D0%9F-2026-029", true],
    ["/erp/catalog", false],
    ["/nowhere/at-all", true],
  ])("%s → %s", (path, expected) => {
    expect(isActionable(path)).toBe(expected);
  });

  it("раздел с родным экраном исполним, а стоит убрать запись моста — адрес становится исполнимым сам", () => {
    const key = "eds.outbox";
    const entry = BRIDGE[key];
    const path = "/eds/outbox/%D0%9A%D0%9F-2026%2F118";
    expect(isActionable(path)).toBe(false);
    // имитация переноса раздела: запись моста удалена
    Reflect.deleteProperty(BRIDGE, key);
    try {
      expect(isActionable(path)).toBe(true);
    } finally {
      (BRIDGE as Record<string, unknown>)[key] = entry;
    }
  });

  it("routeTarget: раздел, объект из пути или ?lead=, запись моста", () => {
    expect(routeTarget("/crm/leads?lead=L-2041&panel=open")).toMatchObject({
      module: "crm",
      section: "leads",
      objectId: "L-2041",
    });
    expect(routeTarget("/eds/drafts/%D0%9A%D0%9F-2026%2F118")?.objectId).toBe("КП-2026/118");
    expect(routeTarget("/eds/inbox")?.entry).toBeUndefined();
    expect(routeTarget("/nowhere")).toBeUndefined();
  });
});
