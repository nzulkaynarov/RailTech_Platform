import { describe, expect, it } from "vitest";

import { MAX_FILE_BYTES, formatFileSize } from "./fileSize";

describe("formatFileSize", () => {
  it("байты, килобайты и мегабайты по языку интерфейса", () => {
    expect(formatFileSize(512, "ru")).toMatch(/^512\s?(байт|Б)/);
    expect(formatFileSize(2048, "ru")).toMatch(/^2\s?кБ/);
    expect(formatFileSize(1.5 * 1024 * 1024, "ru")).toMatch(/^1,5\s?МБ/);
    expect(formatFileSize(1.5 * 1024 * 1024, "en")).toMatch(/^1\.5\s?MB/);
  });

  it("предел вложения — 25 МБ, как в EDS и BFF", () => {
    expect(MAX_FILE_BYTES).toBe(25 * 1024 * 1024);
  });
});
