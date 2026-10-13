import { describe, expect, it } from "vitest";

import { isRowClick } from "./rowClick";

describe("isRowClick", () => {
  const row = document.createElement("div");
  row.innerHTML =
    '<span id="text">Иван</span><a id="link" href="/leads/1"><b id="inner">#1</b></a>' +
    '<button id="btn"><span id="label">Забрать</span></button>';
  it.each([
    ["text", true],
    ["link", false],
    ["inner", false],
    ["btn", false],
    ["label", false],
  ])("%s → %s", (id, expected) => {
    expect(isRowClick(row.querySelector(`#${id}`))).toBe(expected);
  });
  it("treats a missing target as a row click", () => {
    expect(isRowClick(null)).toBe(true);
  });
});
