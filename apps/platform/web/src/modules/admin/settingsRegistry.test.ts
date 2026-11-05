import { describe, expect, it } from "vitest";

import { MENU } from "../../app/rbac.generated";
import { resources } from "../../shared/i18n";
import { admin } from "./module";
import {
  GROUP_NAMES,
  SETTINGS,
  SETTINGS_GROUPS,
  type SettingEntry,
  langOf,
  searchSettings,
} from "./settingsRegistry";

const LANGS = ["ru", "uz", "en"] as const;
/** Слова, которых нет в текстах Настроек (CONVENTIONS §2 п. 17; ресёрч «Настройки» §4.2). */
const FORBIDDEN = /\b(CRM|ERP|EDS)\b|ансамбл|ansambl|ensemble|бэк-офис|back-?office|воркер|getMe/i;

describe("реестр настроек (SET-IA)", () => {
  it("ключи и адреса уникальны; группы — пять, в порядке индекса", () => {
    expect(new Set(SETTINGS.map((s) => s.key)).size).toBe(SETTINGS.length);
    expect(new Set(SETTINGS.map((s) => s.path)).size).toBe(SETTINGS.length);
    expect(SETTINGS_GROUPS).toEqual(["people", "company", "channels", "processes", "system"]);
    // пункты одной группы идут подряд — подменю не перескакивает между группами
    const order = SETTINGS.map((s) => SETTINGS_GROUPS.indexOf(s.group));
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it.each(LANGS)(
    "%s: название = подпись меню и страницы (modules:admin.sections), группа = modules:admin.groups",
    (lng) => {
      const admin = resources[lng].modules.admin as {
        sections: Record<string, string>;
        groups: Record<string, string>;
      };
      for (const entry of SETTINGS) {
        expect(admin.sections[entry.key], `${lng}:${entry.key}`).toBe(entry.name[lng]);
      }
      for (const group of SETTINGS_GROUPS) {
        expect(admin.groups[group], `${lng}:${group}`).toBe(GROUP_NAMES[group][lng]);
      }
    },
  );

  it.each(LANGS)(
    "%s: название до 3 слов, строка карточки до 60 знаков, без названий систем",
    (lng) => {
      for (const entry of SETTINGS) {
        const name = entry.name[lng];
        expect(name.split(/\s+/).length, `${lng}:${entry.key} «${name}»`).toBeLessThanOrEqual(3);
        const line = entry.description[lng];
        expect(line.length, `${lng}:${entry.key} «${line}»`).toBeLessThanOrEqual(60);
        expect(`${name} ${line}`, `${lng}:${entry.key}`).not.toMatch(FORBIDDEN);
        expect(entry.keywords[lng].length, `${lng}:${entry.key}`).toBeGreaterThan(0);
      }
    },
  );

  it("подменю Настроек = реестр (тот же порядок), каталог platform-rbac.yaml знает каждый пункт", () => {
    const menu = admin.sections.filter((s) => !s.hidden && s.key !== "overview");
    expect(menu.map((s) => s.key)).toEqual(SETTINGS.map((s) => s.key));
    expect(menu.map((s) => s.path)).toEqual(SETTINGS.map((s) => s.path));
    expect(Object.keys(MENU.admin)).toEqual(["overview", ...SETTINGS.map((s) => s.key)]);
  });

  it("разделы пунктов: `admin`, `company.settings` и (SIGN-2) `eds.signing.manage` для «Прав подписи»", () => {
    const resourcesOf = (entry: SettingEntry) =>
      "resource" in entry.access ? [entry.access.resource] : [...entry.access.anyOf];
    const used = new Set(SETTINGS.flatMap(resourcesOf));
    expect([...used].sort()).toEqual(["admin", "company.settings", "eds.signing.manage"]);
  });
});

describe("поиск по настройкам", () => {
  const keys = (query: string, allowed?: (e: SettingEntry) => boolean) =>
    searchSettings(query, "ru", allowed).map((hit) => hit.entry.key);

  it("по названию — первым: «почта» → «Почта»; «справоч» → «Справочники»", () => {
    expect(keys("почта")[0]).toBe("mail");
    expect(keys("справоч")[0]).toBe("dictionaries");
  });

  it("по словам внутри страницы, с подсказкой, чем найдено: «курс», «sla», «причины отказа», «imap»", () => {
    expect(keys("курс")).toContain("taxes");
    expect(keys("sla")).toEqual(["timing"]);
    expect(keys("причины отказа")[0]).toBe("dictionaries");
    const imap = searchSettings("imap", "ru");
    expect(imap.map((h) => h.entry.key)).toEqual(["mail"]);
    expect(imap[0]?.matchedBy).toBe("imap");
  });

  it("на любом из трёх языков и без «ё»; каждое слово запроса обязательно", () => {
    expect(keys("mail")).toContain("mail");
    expect(keys("pochta")).toContain("mail");
    expect(keys("расчетный")).toContain("company");
    expect(keys("почта курс")).toEqual([]);
  });

  it("короткий запрос ничего не ищет; недоступное ролям не находится", () => {
    expect(keys("п")).toEqual([]);
    expect(keys("")).toEqual([]);
    expect(keys("обмен", (e) => e.key !== "bus")).not.toContain("bus");
  });

  it("язык интерфейса: uz, en; прочее — ru", () => {
    expect(langOf("uz")).toBe("uz");
    expect(langOf("en-US")).toBe("en");
    expect(langOf("de")).toBe("ru");
    expect(langOf(undefined)).toBe("ru");
  });
});
