import { describe, expect, it } from "vitest";

import type { ComponentStatusOut, SystemStatusOut } from "../api/generated/model";
import {
  bySeverity,
  componentPath,
  criticalFailures,
  headerHealth,
  warningsText,
} from "./systemHealth";

const c = (key: string, status: ComponentStatusOut["status"]): ComponentStatusOut => ({
  key,
  title: key,
  status,
  reason: "",
  checked_at: null,
});
const of = (...components: ComponentStatusOut[]): SystemStatusOut => ({
  status: "ok",
  checked_at: "2026-10-12T09:00:00Z",
  components,
});

describe("headerHealth", () => {
  it.each([
    [of(c("bot", "ok"), c("queue", "ok")), "ok", "Онлайн"],
    [of(c("bot", "ok"), c("queue", "warn")), "warn", "1 предупреждение"],
    [of(c("bot", "fail"), c("queue", "warn")), "fail", "Сбой: бот"],
    [of(c("bot", "ok"), c("models", "unknown")), "ok", "Онлайн"],
  ])("case %#", (status, tone, label) => {
    expect(headerHealth(status)).toEqual({ tone, label });
  });

  it("pluralises warnings", () => {
    expect(warningsText(2)).toBe("2 предупреждения");
    expect(warningsText(5)).toBe("5 предупреждений");
    expect(warningsText(11)).toBe("11 предупреждений");
    expect(warningsText(21)).toBe("21 предупреждение");
  });

  it("banner only for bot and dialog model", () => {
    const status = of(c("bot", "fail"), c("model:dialog-model", "fail"), c("s3", "fail"));
    expect(criticalFailures(status).map((x) => x.key)).toEqual(["bot", "model:dialog-model"]);
  });

  it("sorts fail, warn, unknown, ok", () => {
    const sorted = bySeverity([c("a", "ok"), c("b", "unknown"), c("c", "warn"), c("d", "fail")]);
    expect(sorted.map((x) => x.key)).toEqual(["d", "c", "b", "a"]);
  });
});

describe("componentPath", () => {
  it.each([
    ["bot", "/integrations?tab=bot"],
    ["channel", "/integrations?tab=channel"],
    ["erp", "/integrations?tab=erp"],
    ["model:dialog-model", "/models"],
    ["model:embed-model", "/models"],
    ["backup", "/backups"],
    ["budget", "/spend"],
    ["crm_url", "/settings?section=company"],
    ["database", null],
    ["queue", null],
    ["future", null],
  ])("%s → %s", (key, path) => {
    expect(componentPath(key)).toBe(path);
  });
});
