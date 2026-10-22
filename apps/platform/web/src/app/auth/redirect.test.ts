import { describe, expect, it } from "vitest";

import { DEFAULT_HOME, loginPath, safeNext } from "./redirect";

describe("safeNext: возврат после входа только внутри Платформы", () => {
  it("пропускает внутренние пути с параметрами", () => {
    expect(safeNext("/crm/leads?panel=open")).toBe("/crm/leads?panel=open");
    expect(safeNext("/eds/inbox/%D0%92%D0%A5-104")).toBe("/eds/inbox/%D0%92%D0%A5-104");
  });

  it.each([
    null,
    undefined,
    "",
    "https://evil.example/",
    "//evil.example",
    "/\\evil.example",
    "javascript:alert(1)",
    "crm/leads",
  ])("%s → главная", (value) => {
    expect(safeNext(value)).toBe(DEFAULT_HOME);
  });

  it("сам экран входа и корень не годятся как адрес возврата", () => {
    expect(safeNext("/login?next=/crm")).toBe(DEFAULT_HOME);
    expect(safeNext("/")).toBe(DEFAULT_HOME);
  });

  it("loginPath кодирует адрес возврата", () => {
    expect(loginPath("/crm/leads?panel=open")).toBe("/login?next=%2Fcrm%2Fleads%3Fpanel%3Dopen");
    expect(loginPath("/")).toBe("/login");
    expect(loginPath("/crm/leads", true)).toBe("/login?next=%2Fcrm%2Fleads&reason=expired");
    expect(loginPath("/", true)).toBe("/login?reason=expired");
  });
});
