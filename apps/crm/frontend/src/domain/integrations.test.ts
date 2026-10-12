import { describe, expect, it } from "vitest";

import type { BotProfileOut, TelegramStatusOut } from "../api/generated/model";
import { botState, channelLabel, integrationTabStatus } from "./integrations";

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

describe("integrationTabStatus", () => {
  const status: TelegramStatusOut = {
    channel_id: null,
    channel_title: null,
    configured: true,
    last4: null,
    last_error: null,
    mode: "polling",
    running: true,
    secrets_enabled: true,
    source: "db",
    updated_at: null,
    username: "rt_bot",
  };
  const profile = (published: BotProfileOut["published"]): BotProfileOut => ({
    profile: {},
    published,
  });
  const at = "2026-10-12T10:00:00Z";
  const cases: [string, TelegramStatusOut, BotProfileOut | undefined, (string | null)[]][] = [
    ["running bot, no channel, profile loading", status, undefined, ["success", null, "warning"]],
    [
      "failed bot, channel on, never published",
      { ...status, running: false, last_error: "RuntimeError", channel_id: -100 },
      profile(null),
      ["error", "default", "success"],
    ],
    [
      "published ok",
      status,
      profile({ ok: true, at, changed: 3, error: null, retry_after: null }),
      ["success", "success", "warning"],
    ],
    [
      "publish rate-limited, token not set",
      { ...status, configured: false, running: false },
      profile({ ok: false, at, changed: 0, error: "rate_limited", retry_after: 60 }),
      ["warning", "warning", "warning"],
    ],
  ];

  it.each(cases)("%s", (_name, s, p, [bot, prof, channel]) => {
    expect(integrationTabStatus(s, p)).toEqual({ bot, profile: prof, channel });
  });
});
