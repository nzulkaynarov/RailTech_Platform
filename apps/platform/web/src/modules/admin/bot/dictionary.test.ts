import { describe, expect, it } from "vitest";

import schemas from "../../../mocks/fixtures/botSettingsSchemas.json";
import { resources } from "../../../shared/i18n";
import type { JsonSchema } from "./schemaForm";

/** Тест-сторож словаря: каждое поле и каждый текст бота из схем CRM подписан на трёх языках, без голых ключей. */
const SCHEMAS = schemas as Record<string, JsonSchema>;

function propertyKeys(): {
  fields: string[];
  described: string[];
  texts: string[];
  sections: string[];
} {
  const fields = new Set<string>();
  const described = new Set<string>();
  const walk = (node: JsonSchema | undefined): void => {
    if (!node) return;
    for (const [key, child] of Object.entries(node.properties ?? {})) {
      fields.add(key);
      if (child.description) described.add(key);
      walk(child);
    }
    walk(node.items);
    for (const variant of node.anyOf ?? []) walk(variant);
    for (const def of Object.values(node.$defs ?? {})) walk(def);
  };
  for (const [key, schema] of Object.entries(SCHEMAS)) if (key !== "texts") walk(schema);
  return {
    fields: [...fields],
    described: [...described],
    texts: Object.keys(SCHEMAS["texts"]?.properties ?? {}),
    sections: Object.keys(SCHEMAS),
  };
}

describe("словарь настроек бота", () => {
  const { fields, described, texts, sections } = propertyKeys();

  it.each(["ru", "uz", "en"] as const)(
    "%s: подписаны все разделы, поля, подсказки-единицы и тексты",
    (lng) => {
      const bot = resources[lng].bot as unknown as {
        keys: Record<string, string>;
        fields: Record<string, string>;
        hints: Record<string, string>;
        texts: { items: Record<string, { label: string; when: string }> };
      };
      for (const key of sections) expect(bot.keys[key], `${lng} раздел ${key}`).toBeTruthy();
      for (const key of fields) expect(bot.fields[key], `${lng} поле ${key}`).toBeTruthy();
      expect(bot.fields["consent_version"], `${lng} consent_version`).toBeTruthy();
      // описание поля в схеме CRM — только по-русски: на каждом языке подсказка берётся из словаря
      for (const key of described) expect(bot.hints[key], `${lng} подсказка ${key}`).toBeTruthy();
      for (const key of texts.filter((k) => k !== "consent_version")) {
        expect(bot.texts.items[key]?.label, `${lng} текст ${key}`).toBeTruthy();
        expect(bot.texts.items[key]?.when, `${lng} текст ${key}: когда`).toBeTruthy();
      }
    },
  );

  it("подстановки в подписях «когда» одинаковы во всех языках", () => {
    const placeholders = (text: string) =>
      [...text.matchAll(/\{[a-z_]+\}/g)].map((m) => m[0]).sort();
    const items = (lng: "ru" | "uz" | "en") =>
      (resources[lng].bot as unknown as { texts: { items: Record<string, { when: string }> } })
        .texts.items;
    for (const key of texts.filter((k) => k !== "consent_version")) {
      const ru = placeholders(items("ru")[key]?.when ?? "");
      expect(placeholders(items("uz")[key]?.when ?? ""), `uz ${key}`).toEqual(ru);
      expect(placeholders(items("en")[key]?.when ?? ""), `en ${key}`).toEqual(ru);
    }
  });
});
