import { afterEach, describe, expect, it, vi } from "vitest";

import { firstPanePercent, readSplit, saveSplit } from "./splitSize";

const BOUNDS = { fallback: 65, min: 40, max: 80 };

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("firstPanePercent", () => {
  it.each([
    [[650, 350], 65],
    [[1, 2], 33.3],
    [[300, 100, 100], 60],
    [[0, 500], 0],
  ])("%j → %s", (sizes, expected) => {
    expect(firstPanePercent(sizes)).toBe(expected);
  });

  it.each([[[]], [[500]], [[0, 0]], [[Number.NaN, 10]]])("%j → null", (sizes) => {
    expect(firstPanePercent(sizes)).toBeNull();
  });
});

describe("readSplit / saveSplit", () => {
  it("returns the default when nothing is stored", () => {
    expect(readSplit("lead", BOUNDS)).toBe("65%");
  });

  it("round-trips the first pane share", () => {
    saveSplit("lead", [700, 300]);
    expect(readSplit("lead", BOUNDS)).toBe("70%");
  });

  it.each([
    ["10", "40%"],
    ["95", "80%"],
    ["garbage", "65%"],
  ])("clamps or ignores stored %s → %s", (raw, expected) => {
    window.localStorage.setItem("rt.split.lead", raw);
    expect(readSplit("lead", BOUNDS)).toBe(expected);
  });

  it("keeps the panes separate per key", () => {
    saveSplit("inbox", [500, 500]);
    expect(readSplit("lead", BOUNDS)).toBe("65%");
    expect(readSplit("inbox", BOUNDS)).toBe("50%");
  });

  it("falls back when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => {
      saveSplit("lead", [700, 300]);
    }).not.toThrow();
    expect(readSplit("lead", BOUNDS)).toBe("65%");
  });
});
