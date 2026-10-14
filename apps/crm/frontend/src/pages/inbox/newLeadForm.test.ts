import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/http";
import {
  duplicateOf,
  duplicatePath,
  leadFieldError,
  requiredContact,
  toLeadIn,
} from "./newLeadForm";

describe("toLeadIn", () => {
  it("trims values, turns empty strings into null and defaults the language", () => {
    expect(
      toLeadIn({
        source: "phone",
        name: "  Бобур ",
        company: " ",
        phone: "90 765 43 21",
        email: "",
      }),
    ).toEqual({
      source: "phone",
      name: "Бобур",
      company: null,
      phone: "90 765 43 21",
      email: null,
      need: null,
      language: "ru",
    });
  });

  it("keeps the chosen language and need", () => {
    expect(toLeadIn({ source: "referral", name: "A", need: "POS", language: "uz" })).toMatchObject({
      need: "POS",
      language: "uz",
    });
  });
});

describe("requiredContact", () => {
  it.each([
    ["phone", "phone"],
    ["email", "email"],
    ["referral", "any"],
  ] as const)("%s → %s", (source, expected) => {
    expect(requiredContact(source)).toBe(expected);
  });
});

describe("leadFieldError", () => {
  it("highlights the phone field for invalid_phone", () => {
    const result = leadFieldError(
      new ApiError(422, "validation_failed", "bad", { reason: "invalid_phone", field: "phone" }),
    );
    expect(result?.name).toBe("phone");
    expect(result?.errors[0]).toContain("кодом страны");
  });

  it("returns null for unknown fields and network errors", () => {
    expect(
      leadFieldError(new ApiError(422, "validation_failed", "x", { field: "source" })),
    ).toBeNull();
    expect(leadFieldError(new Error("offline"))).toBeNull();
  });
});

describe("duplicateOf", () => {
  it("offers the existing lead on lead_exists", () => {
    const d = duplicateOf(
      new ApiError(409, "conflict", "exists", {
        reason: "lead_exists",
        lead_id: 42,
        display_name: "Бобур",
        field: "phone",
      }),
    );
    expect(d).toEqual({
      kind: "lead",
      id: 42,
      name: "Бобур",
      text: "Такой телефон или почта уже есть у лида «Бобур»",
    });
    expect(d ? duplicatePath(d) : null).toBe("/leads/42");
  });

  it("offers the client card on client_exists", () => {
    const d = duplicateOf(
      new ApiError(409, "conflict", "exists", {
        reason: "client_exists",
        client_id: 7,
        client_name: "ООО Клиент",
      }),
    );
    expect(d?.kind).toBe("client");
    expect(d?.text).toContain("ООО Клиент");
    expect(d ? duplicatePath(d) : null).toBe("/clients/7");
  });

  it("ignores other conflicts and errors", () => {
    expect(duplicateOf(new ApiError(409, "conflict", "x", { reason: "lead_taken" }))).toBeNull();
    expect(duplicateOf(new ApiError(422, "validation_failed", "x", {}))).toBeNull();
    expect(duplicateOf(new Error("offline"))).toBeNull();
  });
});
