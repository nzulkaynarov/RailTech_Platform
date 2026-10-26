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

  it.each(["common", "shell", "modules", "dictionary", "ui", "integrations", "kb", "bot"] as const)(
    "пространство %s: uz и en — те же ключи, что ru",
    (ns) => {
      for (const lng of ["uz", "en"] as const) {
        expect(keys(resources[lng][ns]).sort()).toEqual(keys(resources.ru[ns]).sort());
      }
    },
  );

  it("нет пустых строк ни в одном языке", () => {
    for (const lng of ["ru", "uz", "en"] as const) {
      for (const ns of [
        "common",
        "shell",
        "modules",
        "dictionary",
        "ui",
        "integrations",
        "kb",
        "bot",
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
