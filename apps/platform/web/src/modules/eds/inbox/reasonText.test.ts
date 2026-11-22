import { describe, expect, it } from "vitest";

import { ApiError } from "../../../shared/api/errors";
import i18n from "../../../shared/i18n";
import { reasonText } from "./api";

const t = i18n.getFixedT("ru", "letters") as (
  key: string,
  options?: Record<string, unknown>,
) => string;

describe("СЦ-7: причина отказа письма", () => {
  it("403 с правом EDS — раздел словами из каталога, без кода права", () => {
    const error = new ApiError(403, "FORBIDDEN", "Действие не положено вашей роли.", "eds", {
      permission: "letters.resolve",
    });
    const text = reasonText(t, error);
    expect(text).toBe("нет доступа к разделу «Документы · Входящие · резолюция»");
    expect(text).not.toContain("letters.resolve");
  });

  it("403 без права — прежняя общая фраза; другие причины не меняются", () => {
    expect(reasonText(t, new ApiError(403, "FORBIDDEN", "x", "eds"))).toBe(
      "действие не положено вашей роли",
    );
    expect(
      reasonText(t, new ApiError(409, "CONFLICT", "x", "eds", { permission: "letters.resolve" })),
    ).toBe("письмо уже не ждёт резолюции, обновите карточку");
  });
});
