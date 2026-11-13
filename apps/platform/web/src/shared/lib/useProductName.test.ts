import { describe, expect, it } from "vitest";

import { initialsOf } from "./useProductName";

describe("initialsOf", () => {
  it("буквы логотипа из названия компании (задача «Н3»)", () => {
    expect(initialsOf("RailTech (демо)")).toBe("RT");
    expect(initialsOf("ООО Ромашка")).toBe("ОР");
    expect(initialsOf("Платформа")).toBe("ПЛ");
    expect(initialsOf("  ")).toBe("");
  });
});
