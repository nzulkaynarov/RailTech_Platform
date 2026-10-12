import { describe, expect, it } from "vitest";

import {
  emptyLanguages,
  fillPlaceholders,
  hasPlaceholders,
  pickerToTime,
  resolveSection,
  sectionGroups,
  textGroups,
  timeToPicker,
  widgetFor,
} from "./settingsLayout";

const ALL = [
  "company",
  "business_hours",
  "texts",
  "escalation",
  "qualification",
  "kb",
  "bot",
  "competitors",
  "stop_words",
  "notifications",
  "budget",
];

describe("settings sections", () => {
  it("groups every section and keeps budget visible", () => {
    const groups = sectionGroups(ALL);
    expect(groups.map((g) => g.key)).toEqual(["company", "bot", "handoff", "team", "spend"]);
    expect(groups.flatMap((g) => g.sections).sort()).toEqual([...ALL].sort());
    expect(groups.at(-1)?.sections).toEqual(["budget"]);
  });

  it("puts unknown sections into «other» instead of dropping them", () => {
    expect(sectionGroups(["company", "new_thing"]).map((g) => g.sections)).toEqual([
      ["company"],
      ["new_thing"],
    ]);
  });

  it.each([
    ["budget", "budget"],
    [null, "company"],
    ["nope", "company"],
  ])("?section=%s → %s", (requested, expected) => {
    expect(resolveSection(requested, ALL)).toBe(expected);
  });

  it("returns null without sections", () => {
    expect(resolveSection("company", [])).toBeNull();
  });
});

describe("bot text groups", () => {
  it("keeps every key, unknown ones in «other»", () => {
    const groups = textGroups(["greeting", "fallback", "brand_new"]);
    expect(groups).toEqual([
      { key: "welcome", fields: ["greeting"] },
      { key: "fallback", fields: ["fallback"] },
      { key: "other", fields: ["brand_new"] },
    ]);
  });
});

describe("widgets", () => {
  it.each([
    ["start", { format: "time" }, "time"],
    ["weekdays", {}, "weekdays"],
    ["holidays", { format: "date" }, "dates"],
    ["timezone", {}, "timezone"],
    ["duty_user_ids", {}, "users"],
    ["disabled_triggers", {}, "triggers"],
    ["name", {}, null],
  ])("%s → %s", (key, schema, expected) => {
    expect(widgetFor(key, schema)).toBe(expected);
  });

  it.each([
    ["09:00:00", "09:00"],
    ["18:30", "18:30"],
    ["", null],
    [null, null],
  ])("time %s → picker %s", (value, expected) => {
    expect(timeToPicker(value)).toBe(expected);
  });

  it("stores picker time in the API format", () => {
    expect(pickerToTime("09:05")).toBe("09:05:00");
  });
});

describe("text preview", () => {
  it("only for texts with placeholders", () => {
    expect(hasPlaceholders("Согласен")).toBe(false);
    expect(hasPlaceholders("Мы работаем {hours}")).toBe(true);
  });

  it("fills known placeholders and keeps unknown ones", () => {
    expect(fillPlaceholders("{company}: {hours} {x}", { company: "RT", hours: "9–18" })).toBe(
      "RT: 9–18 {x}",
    );
  });

  it("finds empty translations", () => {
    expect(emptyLanguages({ ru: "a", uz: " ", en: undefined })).toEqual(["uz", "en"]);
  });
});

describe("textGroups advanced", () => {
  it("puts consent_version into the last «advanced» group", () => {
    const groups = textGroups(["greeting", "consent_version", "brand_new"]);
    expect(groups.map((g) => g.key)).toEqual(["welcome", "other", "advanced"]);
    expect(groups.at(-1)?.fields).toEqual(["consent_version"]);
  });
});
