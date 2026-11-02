import { describe, expect, it } from "vitest";

import i18n, { resources } from "./index";

function keys(obj: object, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null ? keys(v as object, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

describe("i18n", () => {
  it("defaults to Russian", () => {
    expect(i18n.language).toBe("ru");
    expect(i18n.t("app.title")).toBe("Платформа RailTech");
    expect(i18n.t("login.title", { ns: "shell" })).toBe("Вход в Платформу");
  });

  it.each([
    "common",
    "shell",
    "bridge",
    "modules",
    "dictionary",
    "ui",
    "integrations",
    "company",
    "audit",
    "bus",
    "kb",
    "bot",
    "messages",
    "leads",
    "clients",
    "request",
    "documents",
    "letters",
    "calc",
    "profile",
    "quotes",
    "projects",
    "approvals",
    "catalog",
    "payments",
    "help",
    "articles",
  ] as const)("пространство %s: uz и en — те же ключи, что ru", (ns) => {
    for (const lng of ["uz", "en"] as const) {
      expect(keys(resources[lng][ns]).sort()).toEqual(keys(resources.ru[ns]).sort());
    }
  });

  it("нет пустых строк ни в одном языке", () => {
    for (const lng of ["ru", "uz", "en"] as const) {
      for (const ns of [
        "common",
        "shell",
        "bridge",
        "modules",
        "dictionary",
        "ui",
        "integrations",
        "company",
        "audit",
        "bus",
        "kb",
        "bot",
        "messages",
        "leads",
        "clients",
        "request",
        "leads",
        "clients",
        "request",
        "documents",
        "letters",
        "calc",
        "profile",
        "quotes",
        "projects",
        "approvals",
        "catalog",
        "payments",
        "help",
        "articles",
      ] as const) {
        for (const key of keys(resources[lng][ns])) {
          const value = key
            .split(".")
            .reduce<unknown>(
              (acc, part) => (acc as Record<string, unknown>)[part],
              resources[lng][ns],
            );
          expect(value, `${lng}:${ns}:${key}`).not.toBe("");
        }
      }
    }
  });
});

/** Значение по пути `a.b.c` в пространстве имён. */
function valueAt(tree: object, path: string): unknown {
  return path
    .split(".")
    .reduce<unknown>((acc, part) => (acc as Record<string, unknown> | undefined)?.[part], tree);
}

/** Тексты экранов Настроек (CONVENTIONS §2 п. 17, S2; ресёрч 2026-11-02 «Настройки» §4.2). */
const SETTINGS_SUBTITLES = [
  "integrations:subtitle",
  "bot:subtitle",
  "company:subtitle",
  "modules:admin.setup.subtitle",
  "modules:admin.org.subtitle",
  "modules:admin.roles.subtitle",
  "articles:admin.subtitle",
  "audit:page.subtitle",
  "letters:settings.subtitle",
] as const;
const CARD_PURPOSES = [
  "erp",
  "telegram",
  "mail",
  "services",
  "models",
  "spend",
  "storage",
  "system",
] as const;
/** Слова, которых нет в текстах Настроек: названия систем и внутренности — не для сотрудника. */
const JARGON = /ансамбл|ansambl|ensemble|бэк-офис|back-?office|back-?ofis|orqa ofis|getMe|воркер/i;
const SYSTEMS = /\b(CRM|ERP|EDS)\b/;

describe("тексты Настроек коротко и без жаргона (S2)", () => {
  type Ns = keyof (typeof resources)["ru"];
  const at = (lng: "ru" | "uz" | "en", ref: string) => {
    const [ns = "", path = ""] = ref.split(":");
    return valueAt(resources[lng][ns as Ns], path);
  };

  it.each(["ru", "uz", "en"] as const)(
    "%s: подзаголовок ≤ 90 знаков, описание карточки ≤ 60, без CRM/ERP/EDS",
    (lng) => {
      for (const ref of SETTINGS_SUBTITLES) {
        const text = String(at(lng, ref));
        expect(text.length, `${lng}:${ref} «${text}»`).toBeLessThanOrEqual(90);
        expect(text, `${lng}:${ref}`).not.toMatch(SYSTEMS);
      }
      for (const card of CARD_PURPOSES) {
        const text = String(at(lng, `integrations:cards.${card}.purpose`));
        expect(text.length, `${lng}:cards.${card}.purpose «${text}»`).toBeLessThanOrEqual(60);
        expect(text, `${lng}:cards.${card}.purpose`).not.toMatch(SYSTEMS);
      }
    },
  );

  it.each(["ru", "uz", "en"] as const)(
    "%s: в Настройках нет «ансамбля», «бэк-офиса», getMe и «воркера»",
    (lng) => {
      const trees: [string, object][] = [
        ["integrations", resources[lng].integrations],
        ["bot", resources[lng].bot],
        ["company", resources[lng].company],
        ["modules.admin", resources[lng].modules.admin],
      ];
      for (const [name, tree] of trees) {
        for (const key of keys(tree)) {
          const text = valueAt(tree, key);
          if (typeof text === "string") expect(text, `${lng}:${name}.${key}`).not.toMatch(JARGON);
        }
      }
    },
  );
});
