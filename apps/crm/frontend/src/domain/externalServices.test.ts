import { describe, expect, it } from "vitest";

import type { ExternalServiceOut } from "../api/generated/model";
import {
  formatBytes,
  groupOf,
  groupServices,
  manuallyDisabled,
  metricRows,
  percent,
  summaryItems,
} from "./externalServices";

function service(overrides: Partial<ExternalServiceOut> = {}): ExternalServiceOut {
  return {
    key: "telegram",
    title: "Telegram Bot API",
    purpose: "Клиентский бот",
    system: "crm",
    source: "crm",
    check: "getMe",
    frequency: "minute",
    status: "ok",
    summary: "Бот отвечает",
    error: null,
    hint: null,
    fix_path: "/integrations?tab=bot",
    checked_at: "2026-10-14T09:00:00Z",
    stale: false,
    latency_ms: 120,
    metrics: {},
    uptime_24h: 1,
    uptime_7d: 1,
    checks_24h: 1440,
    failures_24h: 0,
    p95_ms_24h: 150,
    switch: null,
    incident: null,
    ...overrides,
  };
}

describe("groupServices", () => {
  it.each([
    [service({ status: "fail" }), "attention"],
    [service({ status: "warn" }), "attention"],
    [service({ status: "unknown", stale: true }), "attention"],
    [service({ status: "ok" }), "working"],
    [service({ status: "off" }), "idle"],
    [service({ status: "unknown" }), "idle"],
    [service({ status: "unknown", source: "erp" }), "erp"],
    [
      service({
        status: "off",
        switch: {
          kind: "vendor",
          available: true,
          disabled: true,
          effect: "",
          problem: null,
          reason: null,
          changed_at: null,
          changed_by: null,
        },
      }),
      "disabled",
    ],
  ] as const)("%# → %s", (s, group) => {
    expect(groupOf(s)).toBe(group);
  });

  it("puts problems first and failures before warnings, drops empty groups", () => {
    const groups = groupServices([
      service({ key: "a", status: "ok" }),
      service({ key: "b", status: "warn" }),
      service({ key: "c", status: "fail" }),
    ]);
    expect(groups.map((g) => g.key)).toEqual(["attention", "working"]);
    expect(groups[0]?.services.map((s) => s.key)).toEqual(["c", "b"]);
  });
});

describe("summaryItems", () => {
  it("keeps «В норме» and non-zero counters in order of importance", () => {
    const items = summaryItems({ ok: 0, warn: 1, fail: 2, unknown: 0, off: 3, disabled: 1 });
    expect(items.map((i) => i.key)).toEqual(["fail", "warn", "ok", "off", "disabled"]);
  });
});

describe("manuallyDisabled", () => {
  it("lists only services switched off by an admin", () => {
    const off = service({
      key: "mail",
      switch: {
        kind: "mail",
        available: true,
        disabled: true,
        effect: "",
        problem: null,
        reason: null,
        changed_at: null,
        changed_by: null,
      },
    });
    expect(manuallyDisabled([service(), off]).map((s) => s.key)).toEqual(["mail"]);
  });
});

describe("metric formatting", () => {
  it("labels known metrics in Russian and skips unknown or empty ones", () => {
    const rows = metricRows({
      calls_24h: 1200,
      error_rate_24h: 0.0125,
      spend_24h_usd: 1.5,
      p95_ms_24h: 950,
      "bucket.kb-sources.bytes": 5 * 1024 * 1024,
      "bucket.kb-sources.objects": 12,
      budget_limit_usd: null,
      something_new: 3,
    });
    expect(rows.map((r) => r.label)).toEqual([
      "Вызовов за 24 ч",
      "Доля ошибок за 24 ч",
      "Расход за 24 ч",
      "Задержка ответа (95 %) за 24 ч",
      "Бакет kb-sources: занято",
      "Бакет kb-sources: файлов",
    ]);
    expect(rows.map((r) => r.value.replace(/\u00a0/g, " "))).toEqual([
      "1 200",
      "1,3 %",
      "$1,50",
      "950 мс",
      "5 МБ",
      "12",
    ]);
  });

  it.each([
    [0, "0 Б"],
    [2048, "2 КБ"],
    [1536 * 1024 * 1024, "1,5 ГБ"],
  ])("formatBytes(%i) = %s", (bytes, text) => {
    expect(formatBytes(bytes).replace(/\u00a0/g, " ")).toBe(text);
  });

  it("percent of uptime, no data — dash", () => {
    expect(percent(0.995).replace(/\u00a0/g, " ")).toBe("99,5 %");
    expect(percent(null)).toBe("—");
  });
});
