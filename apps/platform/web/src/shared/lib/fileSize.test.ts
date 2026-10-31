import { describe, expect, it } from "vitest";

import "../i18n";
import { formatFileSize } from "./fileSize";

describe("formatFileSize", () => {
  it("байты, КБ, МБ и ГБ — основание 1024, единицы из словаря", () => {
    expect(formatFileSize(512, "ru")).toBe("512 Б");
    expect(formatFileSize(2048, "ru")).toBe("2 КБ");
    expect(formatFileSize(1536, "ru")).toBe("1,5 КБ");
    expect(formatFileSize(1.5 * 1024 * 1024, "ru")).toBe("1,5 МБ");
    expect(formatFileSize(3 * 1024 ** 3, "ru")).toBe("3 ГБ");
  });

  it("узбекский и английский", () => {
    expect(formatFileSize(1.5 * 1024 * 1024, "en")).toBe("1.5 MB");
    expect(formatFileSize(2048, "uz")).toBe("2 KB");
  });

  it("ноль и мусор — «0 Б», а не NaN", () => {
    expect(formatFileSize(0, "ru")).toBe("0 Б");
    expect(formatFileSize(Number.NaN, "ru")).toBe("0 Б");
  });
});
