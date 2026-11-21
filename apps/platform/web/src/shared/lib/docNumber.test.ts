import { describe, expect, it } from "vitest";

import { docNumberToPath, isDocNumber } from "./docNumber";

describe("номер документа: непрозрачная строка", () => {
  it.each([
    "IN-104/26",
    "OUT-082/26",
    "RQ-2026-104",
    "PRJ-2026-104",
    "QT-2026/115",
    "MEMO-2026/031",
    "X1",
    // выданные раньше кириллические номера тоже номера: префикс не разбирается
    "ВХ-104/26",
    "ЗВ-2026-104",
    "ПР-2026-104",
    // любое обозначение, которое задаст владелец
    "PR-2026-104",
    "ZZZ-1",
  ])("%s похоже на номер", (text) => {
    expect(isDocNumber(text)).toBe(true);
  });

  it("не номера: без цифры, с пробелом, слишком короткие и длинные", () => {
    for (const text of ["", "IN", "что-то там 1", "a 1", "1", "x".repeat(65) + "1"]) {
      expect(isDocNumber(text), text).toBe(false);
    }
  });

  it("в адресе номер кодируется", () => {
    expect(docNumberToPath("PRJ-2026-104")).toBe("PRJ-2026-104");
    expect(docNumberToPath("IN-104/26")).toBe("IN-104%2F26");
    expect(docNumberToPath("ВХ-104/26")).toBe("%D0%92%D0%A5-104%2F26");
  });
});
