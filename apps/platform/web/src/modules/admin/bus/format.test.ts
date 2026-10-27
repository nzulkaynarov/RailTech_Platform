import { describe, expect, it } from "vitest";

import { mergeSources } from "./format";

describe("mergeSources", () => {
  it("домен без данных на любой странице остаётся «не ответил» на следующих", () => {
    const merged = mergeSources([
      { sources: { crm: "ok", erp: "unavailable", eds: "ok" } },
      { sources: { crm: "ok", erp: "ok", eds: "forbidden" } },
    ]);
    expect(merged).toEqual({ crm: "ok", erp: "unavailable", eds: "forbidden" });
    expect(mergeSources([])).toBeUndefined();
  });
});
