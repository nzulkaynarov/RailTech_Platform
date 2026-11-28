import { describe, expect, it } from "vitest";

import { ApiError } from "../../../shared/api/errors";
import i18n from "../../../shared/i18n";
import { reasonText } from "./errors";

describe("отказы доставки по проекту", () => {
  for (const lng of ["ru", "uz", "en"]) {
    const t = i18n.getFixedT(lng, "projects");
    const generic = reasonText(t, new ApiError(409, "CONFLICT", "x", "erp", {}));
    for (const reason of [
      "delivery_transition_not_allowed",
      "fulfillment_not_ready",
      "goods_not_shipped",
    ]) {
      it(`${lng}: ${reason} — своими словами, а не общим «договор в другом статусе»`, () => {
        const text = reasonText(t, new ApiError(409, "CONFLICT", "x", "erp", { reason }));
        expect(text).not.toBe(generic);
        expect(text).not.toBe(reasonText(t, new ApiError(500, "X", "x")));
      });
    }
  }
  it("ru: доставка в другом статусе", () => {
    const t = i18n.getFixedT("ru", "projects");
    expect(
      reasonText(
        t,
        new ApiError(409, "CONFLICT", "x", "erp", { reason: "delivery_transition_not_allowed" }),
      ),
    ).toBe("Доставка сейчас в другом статусе. Обновите страницу.");
  });
});
