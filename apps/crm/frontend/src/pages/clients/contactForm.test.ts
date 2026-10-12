import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/http";
import { contactFieldError, fromSuggestion, toContactIn, toFormValues } from "./contactForm";

describe("toContactIn", () => {
  it("trims values and turns empty strings into null", () => {
    expect(
      toContactIn({ full_name: "  Алишер ", position: " ", phone: "+998 90 123 45 67", email: "" }),
    ).toEqual({
      full_name: "Алишер",
      position: null,
      phone: "+998 90 123 45 67",
      email: null,
      note: null,
      is_primary: false,
      telegram_identity_id: null,
    });
  });

  it("keeps the telegram link when editing a linked contact", () => {
    expect(toContactIn({ full_name: "A", is_primary: true }, 7)).toMatchObject({
      is_primary: true,
      telegram_identity_id: 7,
    });
  });
});

describe("toFormValues / fromSuggestion", () => {
  it("maps stored E.164 phone into the phone field", () => {
    const values = toFormValues({
      id: 1,
      full_name: "A",
      position: null,
      phone_e164: "+998901234567",
      email: "a@b.uz",
      telegram_identity_id: null,
      is_primary: false,
      note: null,
      created_at: "2026-10-12T00:00:00Z",
    });
    expect(values.phone).toBe("+998901234567");
  });

  it("builds a one-click body from a Telegram suggestion", () => {
    const body = fromSuggestion(
      {
        telegram_identity_id: 3,
        tg_user_id: 42,
        tg_username: null,
        full_name: "Алишер",
        phone_e164: "+998901234567",
      },
      true,
    );
    expect(body).toEqual({
      full_name: "Алишер",
      phone: "+998901234567",
      is_primary: true,
      telegram_identity_id: 3,
    });
  });
});

describe("contactFieldError", () => {
  it("highlights the phone field for invalid_phone", () => {
    const error = new ApiError(422, "validation_failed", "bad", {
      reason: "invalid_phone",
      field: "phone",
    });
    const result = contactFieldError(error);
    expect(result?.name).toBe("phone");
    expect(result?.errors[0]).toContain("кодом страны");
  });

  it("returns null for fields outside the form and for network errors", () => {
    expect(
      contactFieldError(
        new ApiError(422, "validation_failed", "x", { field: "telegram_identity_id" }),
      ),
    ).toBeNull();
    expect(contactFieldError(new Error("offline"))).toBeNull();
  });
});
