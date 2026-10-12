import { describe, expect, it } from "vitest";

import { publishText } from "./botProfile";

const at = "2026-10-12T10:00:00Z";

describe("publishText", () => {
  it("never published", () => {
    const out = publishText(null);
    expect(out.ok).toBe(false);
    expect(out.text).toContain("Ещё не");
  });

  it("published", () => {
    const out = publishText({ ok: true, at, changed: 2, error: null, retry_after: null });
    expect(out.ok).toBe(true);
    expect(out.text).toContain("изменений: 2");
  });

  it.each([
    ["rate_limited", 3600, "через 60 мин"],
    ["rate_limited", 30, "через 1 мин"],
    ["telegram_error", null, "не принял"],
    ["bot_not_running", null, "Бот не запущен"],
  ] as const)("%s", (error, retry, text) => {
    const out = publishText({ ok: false, at, changed: 0, error, retry_after: retry });
    expect(out.ok).toBe(false);
    expect(out.text).toContain(text);
    expect(out.text).not.toContain("{");
  });
});
