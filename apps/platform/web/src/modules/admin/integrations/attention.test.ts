import { describe, expect, it } from "vitest";

import type { AttentionItem, ServiceGroup } from "../../../shared/api/generated/model";
import { mergeSameCause } from "./attention";

const STALE = "Фоновые проверки остановились. Отправьте хостингу: «Запустить фоновые проверки»";

function group(id: string, patch: Partial<ServiceGroup> = {}): ServiceGroup {
  return {
    id,
    state: "not_checked",
    owner: "hosting",
    action: "recheck",
    more_actions: [],
    headline: `Последняя проверка ${id} — фоновые проверки не идут`,
    detail: STALE,
    affected: [],
    service_keys: [id],
    titles: [id],
    since: null,
    technical: [],
    flaps_24h: 0,
    message: null,
    fix_card: null,
    ...patch,
  };
}

function item(g: ServiceGroup, severity: AttentionItem["severity"] = "warn"): AttentionItem {
  return {
    id: `group:${g.id}`,
    card: "services",
    severity,
    kind: "service",
    subject: g.headline,
    detail: g.detail,
    group: g,
    technical: null,
  };
}

describe("mergeSameCause — одинаковые причины одной строкой (S3)", () => {
  it("строки с той же причиной и тем же действием сливаются в первую: сервисы, затронутое, сбои и «с …» — вместе", () => {
    const merged = mergeSameCause([
      item(group("a", { affected: ["диалог"], since: "2026-10-28T11:38:00Z", flaps_24h: 1 })),
      item(group("b", { affected: ["диалог", "поиск"], technical: ["b: stale"] })),
      item(group("c", { since: "2026-10-28T10:00:00Z", flaps_24h: 3, technical: ["c: stale"] })),
    ]);
    expect(merged).toHaveLength(1);
    const only = merged[0]?.group;
    expect(merged[0]?.id).toBe("group:a");
    expect(only?.service_keys).toEqual(["a", "b", "c"]);
    expect(only?.titles).toEqual(["a", "b", "c"]);
    expect(only?.affected).toEqual(["диалог", "поиск"]);
    expect(only?.technical).toEqual(["b: stale", "c: stale"]);
    expect(only?.since).toBe("2026-10-28T10:00:00Z");
    expect(only?.flaps_24h).toBe(3);
  });

  it("другая причина, другое действие, другая важность и строки без группы не сливаются; порядок сохраняется", () => {
    const broken = item(
      group("x", { detail: "Ключ отклонён", state: "broken", action: "enter_key" }),
      "fail",
    );
    const plain: AttentionItem = {
      ...item(group("p")),
      id: "paused:p",
      kind: "paused",
      group: null,
    };
    const otherAction = item(group("y", { action: "open_settings" }));
    const otherSeverity = item(group("z"), "fail");
    const merged = mergeSameCause([
      broken,
      item(group("a")),
      plain,
      otherAction,
      otherSeverity,
      item(group("b")),
    ]);
    expect(merged.map((row) => row.id)).toEqual([
      "group:x",
      "group:a",
      "paused:p",
      "group:y",
      "group:z",
    ]);
    expect(merged[1]?.group?.service_keys).toEqual(["a", "b"]);
  });

  it("строка без текста причины не сливается с другой такой же", () => {
    const merged = mergeSameCause([
      item(group("a", { detail: null })),
      item(group("b", { detail: null })),
    ]);
    expect(merged).toHaveLength(2);
  });
});
