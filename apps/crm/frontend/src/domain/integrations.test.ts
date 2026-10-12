import { describe, expect, it } from "vitest";

import { botState, channelLabel } from "./integrations";

describe("botState", () => {
  it.each([
    [{ configured: true, running: true, last_error: null }, "running"],
    [{ configured: false, running: false, last_error: null }, "notConfigured"],
    [{ configured: true, running: false, last_error: "RuntimeError" }, "failed"],
    [{ configured: true, running: false, last_error: null }, "stopped"],
  ] as const)("%o → %s", (status, expected) => {
    expect(botState(status)).toBe(expected);
  });
});

describe("channelLabel", () => {
  it("prefers the detected title", () => {
    expect(channelLabel(-100, "Команда", "канал {id}")).toBe("Команда");
  });
  it("falls back to id", () => {
    expect(channelLabel(-100, null, "канал {id}")).toBe("канал -100");
  });
  it("returns null without channel", () => {
    expect(channelLabel(null, null, "канал {id}")).toBeNull();
  });
});
