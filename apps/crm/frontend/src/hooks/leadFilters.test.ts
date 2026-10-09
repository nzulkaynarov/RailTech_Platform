import { describe, expect, it } from "vitest";

import { leadFiltersToSearch, parseLeadFilters, toListParams } from "./leadFilters";

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
