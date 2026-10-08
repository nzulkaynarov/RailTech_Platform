import { describe, expect, it } from "vitest";

import { type JsonSchema, kindOf, normalize, resolve } from "./schemaForm";

const root: JsonSchema = {
  $defs: {
    LocalizedText: {
      properties: { ru: { type: "string" }, uz: { type: "string" }, en: { type: "string" } },
    },
  },
  properties: {
    greeting: { $ref: "#/$defs/LocalizedText" },
    channel_id: { anyOf: [{ type: "integer" }, { type: "null" }] },
    duty_user_ids: { type: "array", items: { type: "integer" } },
    terms: { type: "array", items: { type: "string" } },
    min_score: { type: "number", minimum: 0, maximum: 1 },
  },
};

describe("schemaForm", () => {
  it("resolves refs and nullable unions", () => {
    const props = root.properties ?? {};
    expect(kindOf(resolve(props["greeting"] ?? {}, root).schema)).toBe("localized");
    const channel = resolve(props["channel_id"] ?? {}, root);
    expect([kindOf(channel.schema), channel.nullable]).toEqual(["integer", true]);
    expect(kindOf(props["duty_user_ids"] ?? {})).toBe("number-tags");
    expect(kindOf(props["terms"] ?? {})).toBe("tags");
  });

  it("normalizes form values for the API", () => {
    const values = {
      greeting: { ru: "a", uz: "b", en: "c" },
      channel_id: "",
      duty_user_ids: ["5", "7"],
      terms: ["x"],
      min_score: 0.5,
    };
    expect(normalize(values, root, root)).toEqual({
      greeting: { ru: "a", uz: "b", en: "c" },
      channel_id: null,
      duty_user_ids: [5, 7],
      terms: ["x"],
      min_score: 0.5,
    });
  });
});
