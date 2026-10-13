import { describe, expect, it } from "vitest";

import {
  activeFilterCount,
  hiddenFilterCount,
  leadFiltersToSearch,
  parseLeadFilters,
  sortFromHeader,
  sortOrderOf,
  toListParams,
} from "./leadFilters";

describe("lead filters in URL", () => {
  it("round-trips through the query string", () => {
    const search = new URLSearchParams("stage=won&owner=me&min_score=60&page=3&sort=score");
    const filters = parseLeadFilters(search);
    expect(filters).toMatchObject({ stage: "won", owner: "me", min_score: 60, page: 3 });
    expect(leadFiltersToSearch(filters).toString()).toBe(
      "stage=won&owner=me&min_score=60&sort=score&page=3",
    );
  });

  it.each([
    ["min_score=500", { min_score: undefined }],
    ["sort=drop_table", { sort: undefined }],
    ["page=-2", { page: 1 }],
    ["from=yesterday", { from: undefined }],
  ])("ignores invalid %s", (query, expected) => {
    expect(parseLeadFilters(new URLSearchParams(query))).toMatchObject(expected);
  });

  it("maps period to Tashkent day bounds and page to offset", () => {
    const params = toListParams(
      parseLeadFilters(new URLSearchParams("from=2026-10-01&to=2026-10-31&page=2")),
    );
    expect(params).toMatchObject({
      created_from: "2026-10-01T00:00:00+05:00",
      created_to: "2026-11-01T00:00:00+05:00",
      offset: 50,
      limit: 50,
      sort: "last_message",
    });
  });
});

describe("activeFilterCount", () => {
  it.each([
    [{ page: 1 }, 0],
    [{ page: 2, sort: "score" }, 0],
    [{ page: 1, q: "abc", stage: "new" }, 2],
    [{ page: 1, min_score: 0, from: "2026-10-01", to: "2026-10-12" }, 2],
  ])("%j → %i", (f, n) => {
    expect(activeFilterCount(f)).toBe(n);
  });
});

describe("hiddenFilterCount («Ещё фильтры»)", () => {
  it.each([
    [{ page: 1 }, 0],
    [{ page: 1, q: "x", stage: "won", owner: "me" }, 0],
    [{ page: 1, sort: "score" }, 0],
    [{ page: 1, language: "uz" }, 1],
    [{ page: 1, min_score: 0 }, 1],
    [{ page: 1, from: "2026-10-01", to: "2026-10-12" }, 1],
    [{ page: 1, stage: "new", language: "en", min_score: 40, from: "2026-10-01" }, 3],
  ])("%j → %i", (f, n) => {
    expect(hiddenFilterCount(f)).toBe(n);
  });
});

describe("sort by column header", () => {
  it.each([
    [{ columnKey: "score", order: "descend" as const }, "score"],
    [{ columnKey: "score", order: undefined }, undefined],
    [{ columnKey: "score", order: null }, undefined],
    [{ columnKey: "last_message", order: "descend" as const }, undefined],
    [{ columnKey: "need", order: "descend" as const }, undefined],
    [{ columnKey: undefined, order: "descend" as const }, undefined],
  ])("%j → sort=%s", (sorter, sort) => {
    expect(sortFromHeader(sorter)).toBe(sort);
  });

  it.each([
    ["score", undefined, null],
    ["last_message", undefined, "descend"],
    ["score", "score", "descend"],
    ["last_message", "score", null],
    ["score", "created", null],
    ["last_message", "created", null],
  ])("column %s with sort=%s shows %s", (column, sort, order) => {
    expect(sortOrderOf(column, sort)).toBe(order);
  });
});
