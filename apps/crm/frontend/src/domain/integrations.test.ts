import { describe, expect, it } from "vitest";

import type { BotProfileOut, ErpStatusOut, TelegramStatusOut } from "../api/generated/model";
import {
  botState,
  channelLabel,
  erpState,
  erpTabStatus,
  integrationTabStatus,
} from "./integrations";

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

describe("erpState / erpTabStatus", () => {
  const base: ErpStatusOut = {
    configured: false,
    mode: "local",
    base_url: "",
    base_url_source: "none",
    token_configured: false,
    token_source: "none",
    token_last4: null,
    token_updated_at: null,
    webhook_secret_configured: false,
    webhook_secret_source: "none",
    webhook_secret_last4: null,
    webhook_secret_updated_at: null,
    secrets_enabled: true,
  };
  it.each([
    ["nothing", base, "notConfigured", "default"],
    ["url only", { ...base, base_url: "https://erp" }, "partial", "warning"],
    ["token only", { ...base, token_configured: true, token_source: "env" }, "partial", "warning"],
    [
      "both",
      { ...base, configured: true, mode: "erp", base_url: "https://erp", token_configured: true },
      "configured",
      "success",
    ],
  ] as const)("%s → %s / %s", (_name, status, state, tab) => {
    expect(erpState(status)).toBe(state);
    expect(erpTabStatus(status)).toBe(tab);
  });

  it("has no badge while the status is loading", () => {
    expect(erpTabStatus(undefined)).toBeNull();
  });
});
