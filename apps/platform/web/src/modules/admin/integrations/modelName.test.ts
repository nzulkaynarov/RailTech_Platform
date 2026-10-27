import { describe, expect, it } from "vitest";

import { bareModelName } from "./modelName";

describe("bareModelName", () => {
  it("снимает префикс самого провайдера", () => {
    expect(bareModelName("anthropic", "anthropic/claude-haiku-5-5")).toBe("claude-haiku-5-5");
    expect(bareModelName("gemini", "Gemini/gemini-3.8-flash")).toBe("gemini-3.8-flash");
  });

  it("имя без префикса, чужой префикс и пустое остаются как есть", () => {
    expect(bareModelName("anthropic", "claude-haiku-5-5")).toBe("claude-haiku-5-5");
    expect(bareModelName("openai", "anthropic/claude-x")).toBe("anthropic/claude-x");
    expect(bareModelName(null, "anthropic/claude-x")).toBe("anthropic/claude-x");
    expect(bareModelName("anthropic", null)).toBe("");
  });
});
