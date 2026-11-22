import { describe, expect, it } from "vitest";

import { signedByAfter } from "./signedBy";

describe("signedByAfter", () => {
  it("follows the chosen person while the text is empty or was put in by the previous choice", () => {
    expect(signedByAfter("", "", "Демо Клиентов")).toBe("Демо Клиентов");
    expect(signedByAfter("Демо Клиентов", "Демо Клиентов", "Каримова Дилноза")).toBe(
      "Каримова Дилноза",
    );
  });
  it("is cleared when the person or company goes", () => {
    expect(signedByAfter("Демо Клиентов", "Демо Клиентов", null)).toBe("");
  });
  it("never touches a name typed by hand", () => {
    expect(signedByAfter("Иванов И. И.", "Демо Клиентов", "Каримова Дилноза")).toBe("Иванов И. И.");
    expect(signedByAfter("Иванов И. И.", "", null)).toBe("Иванов И. И.");
  });
});
