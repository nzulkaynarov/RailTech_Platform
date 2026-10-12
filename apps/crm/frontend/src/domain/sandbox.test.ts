import { describe, expect, it } from "vitest";

import type { SandboxWhy } from "../api/generated/model";
import { decisionLabel, whyLines } from "./sandbox";

const base: SandboxWhy = {
  decision: "answer",
  reason: null,
  best_score: null,
  documents: [],
  triggers: [],
  priority: null,
};

describe("sandbox why", () => {
  it.each([
    ["answer", "ответ по базе знаний"],
    ["handoff", "передача менеджеру"],
    ["new_action", "new_action"],
  ])("decision %s → %s", (decision, label) => {
    expect(decisionLabel(decision)).toBe(label);
  });

  it("shows only known facts", () => {
    expect(whyLines(base)).toEqual([
      "Решение: ответ по базе знаний",
      "Документы базы знаний: не найдены",
    ]);
  });

  it("lists documents, score and triggers", () => {
    const lines = whyLines({
      ...base,
      decision: "handoff",
      reason: "price",
      best_score: 0.8123,
      documents: ["Прайс", "Сроки"],
      triggers: ["human_requested"],
    });
    expect(lines).toEqual([
      "Решение: передача менеджеру",
      "Причина: price",
      "Совпадение с базой знаний: 0.81",
      "Документы базы знаний: Прайс, Сроки",
      "Сработали правила передачи: human_requested",
    ]);
  });
});
