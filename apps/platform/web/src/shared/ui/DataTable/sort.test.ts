import { describe, expect, it } from "vitest";

import { formatSort, nextSort, parseSort, sortRows } from "./sort";

describe("parseSort", () => {
  const allowed = ["number", "due_date"];

  it("reads ascending and descending order", () => {
    expect(parseSort("number", allowed)).toEqual({ key: "number", dir: "asc" });
    expect(parseSort("-due_date", allowed)).toEqual({ key: "due_date", dir: "desc" });
  });

  it("rejects a field that no column declares", () => {
    expect(parseSort("password", allowed)).toBeNull();
    expect(parseSort("-offers__base_price", allowed)).toBeNull();
    expect(parseSort("", allowed)).toBeNull();
    expect(parseSort(null, allowed)).toBeNull();
  });

  it("round-trips through formatSort", () => {
    expect(formatSort(parseSort("-number", allowed))).toBe("-number");
    expect(formatSort(null)).toBeNull();
  });
});

describe("nextSort", () => {
  it("cycles ascending, descending, off", () => {
    const first = nextSort(null, "a");
    expect(first).toEqual({ key: "a", dir: "asc" });
    const second = nextSort(first, "a");
    expect(second).toEqual({ key: "a", dir: "desc" });
    expect(nextSort(second, "a")).toBeNull();
  });

  it("another column starts ascending", () => {
    expect(nextSort({ key: "a", dir: "desc" }, "b")).toEqual({ key: "b", dir: "asc" });
  });
});

describe("sortRows", () => {
  const name = (row: { n: string | null }) => row.n;

  it("compares text by locale and numbers inside text by value", () => {
    const rows = [{ n: "СЗ-10" }, { n: "СЗ-2" }, { n: "апрель" }, { n: "Борт" }];
    expect(sortRows(rows, name, "asc", "ru").map((r) => r.n)).toEqual([
      "апрель",
      "Борт",
      "СЗ-2",
      "СЗ-10",
    ]);
  });

  it("compares numbers and dates by value, not as text", () => {
    const nums = [{ v: 100 }, { v: 9 }, { v: 25 }];
    expect(sortRows(nums, (r) => r.v, "asc", "ru").map((r) => r.v)).toEqual([9, 25, 100]);
    const dates = [
      { v: new Date("2026-03-01") },
      { v: new Date("2025-12-31") },
      { v: new Date("2026-01-15") },
    ];
    expect(
      sortRows(dates, (r) => r.v, "desc", "ru").map((r) => r.v.toISOString().slice(0, 10)),
    ).toEqual(["2026-03-01", "2026-01-15", "2025-12-31"]);
  });

  it("keeps empty values last in both directions", () => {
    const rows = [{ n: null }, { n: "б" }, { n: "" }, { n: "а" }];
    expect(sortRows(rows, name, "asc", "ru").map((r) => r.n)).toEqual(["а", "б", null, ""]);
    expect(sortRows(rows, name, "desc", "ru").map((r) => r.n)).toEqual(["б", "а", null, ""]);
  });

  it("is stable for equal values", () => {
    const rows = [
      { n: "а", id: 1 },
      { n: "а", id: 2 },
      { n: "а", id: 3 },
    ];
    expect(sortRows(rows, (r) => r.n, "desc", "ru").map((r) => r.id)).toEqual([1, 2, 3]);
  });
});
