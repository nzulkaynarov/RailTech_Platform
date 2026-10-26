import { describe, expect, it } from "vitest";

import schemas from "../../../mocks/fixtures/botSettingsSchemas.json";
import values from "../../../mocks/fixtures/botSettingsValues.json";
import { type JsonSchema, bounds, kindOf, normalize, resolve, withoutFields } from "./schemaForm";
import {
  emptyLanguages,
  errorPaths,
  fillPlaceholders,
  hasPlaceholders,
  isShortField,
  matchesText,
  pickerToTime,
  resolveSection,
  sectionGroups,
  textGroups,
  timeToPicker,
  widgetFor,
} from "./sections";

const SCHEMAS = schemas as Record<string, JsonSchema>;
const KEYS = Object.keys(SCHEMAS);

describe("разделы настроек", () => {
  it("четырнадцать разделов CRM раскладываются по группам без потерь", () => {
    expect(KEYS).toHaveLength(14);
    const grouped = sectionGroups(KEYS).flatMap((g) => g.sections);
    expect([...grouped].sort()).toEqual([...KEYS].sort());
    expect(sectionGroups(KEYS).map((g) => g.key)).toEqual([
      "company",
      "bot",
      "handoff",
      "team",
      "spend",
    ]);
  });

  it("новый раздел CRM попадает в «Другое», пустые группы не показываются", () => {
    const groups = sectionGroups(["company", "future_section"]);
    expect(groups).toEqual([
      { key: "company", sections: ["company"] },
      { key: "other", sections: ["future_section"] },
    ]);
  });

  it("раздел из адреса: известный, шаблоны, выгрузки; чужой — первый по порядку", () => {
    expect(resolveSection("escalation", KEYS)).toBe("escalation");
    expect(resolveSection("templates", KEYS)).toBe("templates");
    expect(resolveSection("exports", KEYS)).toBe("exports");
    expect(resolveSection("nope", KEYS)).toBe("company");
    expect(resolveSection(null, [])).toBeNull();
  });

  it("тексты бота: каждый ключ схемы texts в какой-то группе, порядок групп", () => {
    const keys = Object.keys(SCHEMAS["texts"]?.properties ?? {});
    expect(keys.length).toBeGreaterThan(80);
    const groups = textGroups(keys);
    expect(groups.flatMap((g) => g.fields).sort()).toEqual([...keys].sort());
    expect(groups.map((g) => g.key)[0]).toBe("welcome");
    expect(textGroups(["greeting", "brand_new_text"]).map((g) => g.key)).toEqual([
      "welcome",
      "other",
    ]);
  });
});

describe("схема формы", () => {
  it("locale-текст, объект, перечисления, списки и nullable определяются по схеме CRM", () => {
    const texts = SCHEMAS["texts"] as JsonSchema;
    const greeting = resolve(texts.properties?.["greeting"] ?? {}, texts).schema;
    expect(kindOf(greeting)).toBe("localized");
    const qualification = SCHEMAS["qualification"] as JsonSchema;
    expect(kindOf(qualification.properties?.["required_facts"] ?? {})).toBe("multi-enum");
    expect(kindOf(qualification.properties?.["timeline_max"] ?? {})).toBe("enum");
    const hours = SCHEMAS["business_hours"] as JsonSchema;
    expect(kindOf(hours.properties?.["weekdays"] ?? {})).toBe("number-tags");
    expect(kindOf(hours.properties?.["holidays"] ?? {})).toBe("tags");
    const budget = SCHEMAS["budget"] as JsonSchema;
    expect(kindOf(resolve(budget.properties?.["providers"] ?? {}, budget).schema)).toBe("object");
    const notifications = SCHEMAS["notifications"] as JsonSchema;
    expect(resolve(notifications.properties?.["channel_id"] ?? {}, notifications).nullable).toBe(
      true,
    );
  });

  it("значения по умолчанию CRM проходят normalize без изменений, кроме пустых nullable", () => {
    for (const key of KEYS) {
      const schema = SCHEMAS[key] as JsonSchema;
      const current = (values as Record<string, unknown>)[key];
      expect(normalize(current, schema, schema), key).toEqual(current);
    }
  });

  it("normalize: числа из тегов, пустой nullable — null, лишние поля отбрасываются", () => {
    const notifications = SCHEMAS["notifications"] as JsonSchema;
    expect(
      normalize(
        { channel_id: "", duty_user_ids: ["4", "x", 7], manager_dm_throttle_minutes: 5, extra: 1 },
        notifications,
        notifications,
      ),
    ).toEqual({ channel_id: null, duty_user_ids: [4, 7], manager_dm_throttle_minutes: 5 });
  });

  it("withoutFields скрывает поле, но не из схемы нормализации; bounds — границы числа", () => {
    const notifications = SCHEMAS["notifications"] as JsonSchema;
    expect(Object.keys(withoutFields(notifications, ["channel_id"]).properties ?? {})).toEqual([
      "duty_user_ids",
      "manager_dm_throttle_minutes",
    ]);
    const kb = SCHEMAS["kb"] as JsonSchema;
    expect(bounds(kb.properties?.["min_score"] ?? {})).toEqual({ min: 0, max: 1 });
  });
});

describe("поля и тексты", () => {
  it("виджеты по имени и формату поля", () => {
    expect(widgetFor("start", { format: "time" })).toBe("time");
    expect(widgetFor("weekdays", {})).toBe("weekdays");
    expect(widgetFor("holidays", {})).toBe("dates");
    expect(widgetFor("timezone", {})).toBe("timezone");
    expect(widgetFor("duty_user_ids", {})).toBe("users");
    expect(widgetFor("disabled_triggers", {})).toBe("triggers");
    expect(widgetFor("sla_minutes", {})).toBeNull();
  });

  it("время для выбора и обратно, плейсхолдеры с примерами, пустые переводы", () => {
    expect(timeToPicker("09:00:00")).toBe("09:00");
    expect(timeToPicker(null)).toBeNull();
    expect(pickerToTime("18:30")).toBe("18:30:00");
    expect(hasPlaceholders("Ответим за {minutes} мин")).toBe(true);
    expect(hasPlaceholders("Ответим скоро")).toBe(false);
    expect(fillPlaceholders("{manager} на связи, {unknown}", { manager: "Анна" })).toBe(
      "Анна на связи, {unknown}",
    );
    expect(emptyLanguages({ ru: "а", uz: " ", en: "" })).toEqual(["uz", "en"]);
  });

  it("короткие поля — числа и переключатели; списки и особые виджеты — на всю ширину", () => {
    const escalation = SCHEMAS["escalation"] as JsonSchema;
    expect(isShortField("sla_minutes", escalation.properties?.["sla_minutes"] ?? {})).toBe(true);
    expect(
      isShortField("human_request_terms", escalation.properties?.["human_request_terms"] ?? {}),
    ).toBe(false);
    expect(
      isShortField("disabled_triggers", escalation.properties?.["disabled_triggers"] ?? {}),
    ).toBe(false);
    const hours = SCHEMAS["business_hours"] as JsonSchema;
    expect(isShortField("start", hours.properties?.["start"] ?? {})).toBe(true);
  });

  it("поиск текстов и пути ошибок сервера", () => {
    expect(matchesText("greeting", "прив", "Приветствие", "После /start")).toBe(true);
    expect(matchesText("greeting", "/start", "Приветствие", "После /start")).toBe(true);
    expect(matchesText("greeting", "оплата", "Приветствие", "После /start")).toBe(false);
    expect(matchesText("greeting", "  ", "а", "б")).toBe(true);
    expect(errorPaths({ paths: ["greeting.uz", "", 4, "help.en"] })).toEqual([
      ["greeting", "uz"],
      ["help", "en"],
    ]);
    expect(errorPaths({})).toEqual([]);
  });
});
