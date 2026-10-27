import { describe, expect, it } from "vitest";

import { resources } from "../../shared/i18n";
import { auditChanges, scalarText } from "./changes";
import { AUDIT_ACTIONS, AUDIT_ENTITIES, actionKey } from "./labels";

describe("слова к кодам журнала", () => {
  const lookup = (tree: unknown, path: string): unknown =>
    path
      .split(".")
      .reduce<unknown>((acc, part) => (acc as Record<string, unknown> | undefined)?.[part], tree);

  it.each(["ru", "uz", "en"] as const)(
    "%s: у каждого известного действия и объекта есть слово",
    (lng) => {
      const dict = resources[lng].audit;
      for (const code of AUDIT_ACTIONS) {
        expect(lookup(dict.actions, actionKey(code)), `${lng} ${code}`).toEqual(expect.any(String));
      }
      for (const type of AUDIT_ENTITIES) {
        expect(lookup(dict.entities, type), `${lng} ${type}`).toEqual(expect.any(String));
      }
    },
  );

  it("лишние точки в коде заменяются, чтобы ключ не вложился глубже", () => {
    expect(actionKey("integrations.erp.pair")).toBe("integrations.erp_pair");
    expect(actionKey("user.update")).toBe("user.update");
    expect(actionKey("noprefix")).toBe("noprefix");
  });
});

describe("auditChanges", () => {
  it("только отличающиеся поля, вложенные — путями", () => {
    expect(
      auditChanges(
        { is_active: true, access: { a: "read", b: "full" }, same: 1 },
        { is_active: false, access: { a: "read", b: "read" }, same: 1 },
      ),
    ).toEqual([
      { path: "is_active", before: true, after: false },
      { path: "access.b", before: "full", after: "read" },
    ]);
  });

  it("создание — только «после», удаление — только «до»; id ролей скрыты", () => {
    expect(auditChanges(null, { email: "a@demo.example", platform_role_ids: [1] })).toEqual([
      { path: "email", after: "a@demo.example" },
    ]);
    expect(auditChanges({ email: "a@demo.example" }, undefined)).toEqual([
      { path: "email", before: "a@demo.example" },
    ]);
  });
});

describe("scalarText", () => {
  it("пустое — null, списки через запятую, длинное обрезается", () => {
    expect(scalarText(null)).toBeNull();
    expect(scalarText("")).toBeNull();
    expect(scalarText([])).toBeNull();
    expect(scalarText(["a", "b"])).toBe("a, b");
    expect(scalarText(5)).toBe("5");
    expect(scalarText("x".repeat(200))).toHaveLength(160);
  });
});

describe("фильтр «Объект» журнала (O-6 гейта C2a, W15-H4)", () => {
  it.each(["ru", "uz", "en"] as const)(
    "%s: у каждого объекта своё слово — без двух одинаковых вариантов",
    (lng) => {
      const entities = resources[lng].audit.entities as Record<string, string>;
      const words = AUDIT_ENTITIES.map((type) => entities[type] ?? type);
      expect(new Set(words).size).toBe(words.length);
    },
  );
});
