import { describe, expect, it } from "vitest";

import { formatBytes } from "./backups";

describe("formatBytes", () => {
  it.each([
    [0, "0 Б"],
    [1023, "1023 Б"],
    [1024, "1,0 КБ"],
    [5 * 1024 * 1024 + 512 * 1024, "5,5 МБ"],
    [3 * 1024 ** 3, "3,0 ГБ"],
  ])("%d → %s", (bytes, text) => {
    expect(formatBytes(bytes)).toBe(text);
  });
});
