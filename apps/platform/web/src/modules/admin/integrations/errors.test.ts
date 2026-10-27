import { describe, expect, it } from "vitest";

import { ApiError } from "../../../shared/api/errors";
import i18n from "../../../shared/i18n";
import {
  failedFields,
  hasFailedField,
  integrationErrorText,
  isForbidden,
  isWrongPassword,
} from "./errors";

const t = i18n.getFixedT("ru");

function error(status: number, code: string, details: Record<string, unknown> = {}) {
  return new ApiError(status, code, "сообщение BFF", "crm", details);
}

describe("integrationErrorText", () => {
  it("подкод CRM важнее кода BFF: видно, почему проверка не прошла", () => {
    expect(
      integrationErrorText(t, error(502, "INTEGRATION_FAILED", { reason: "smtp_auth_failed" })),
    ).toBe("Почтовый сервер не принял логин или пароль.");
    expect(
      integrationErrorText(t, error(422, "VALIDATION_FAILED", { reason: "erp_invalid_url" })),
    ).toBe("Адрес ERP указан неверно.");
  });

  it("код BFF без известного подкода — свой текст; неизвестное — общий", () => {
    expect(
      integrationErrorText(t, error(422, "WRONG_PASSWORD", { reason: "wrong_password" })),
    ).toBe("Пароль указан неверно.");
    expect(integrationErrorText(t, error(409, "SECRETS_KEY_MISSING"))).toMatch(/ключ шифрования/);
    expect(
      integrationErrorText(t, error(502, "INTEGRATION_FAILED", { reason: "no_such_reason" })),
    ).toBe("Проверка не прошла: сервис не ответил или отказал.");
    expect(integrationErrorText(t, error(500, "SOMETHING_NEW"))).toBe(
      "Не удалось выполнить действие. Повторите позже.",
    );
    expect(integrationErrorText(t, new Error("boom"))).toBe(
      "Не удалось выполнить действие. Повторите позже.",
    );
  });

  it("422 с названным полем — текст про поле, а не общее «Проверьте заполнение»", () => {
    expect(integrationErrorText(t, error(422, "VALIDATION_FAILED", { fields: ["model"] }))).toMatch(
      /Имя модели не принято/,
    );
    expect(
      integrationErrorText(t, error(422, "VALIDATION_FAILED", { fields: ["api_key"] })),
    ).toMatch(/от 8 до 512/);
    // поле без собственного текста и 422 без полей — общий текст кода
    expect(integrationErrorText(t, error(422, "VALIDATION_FAILED", { fields: ["host"] }))).toBe(
      "Проверьте заполнение полей.",
    );
    expect(integrationErrorText(t, error(422, "VALIDATION_FAILED"))).toBe(
      "Проверьте заполнение полей.",
    );
    expect(failedFields(error(422, "VALIDATION_FAILED", { fields: ["model", 3] }))).toEqual([
      "model",
    ]);
    expect(hasFailedField(new Error("x"), "model")).toBe(false);
  });

  it("тексты не содержат ничего из тела ошибки BFF (секретов там нет, но и показывать его не нужно)", () => {
    const text = integrationErrorText(
      t,
      error(422, "VALIDATION_FAILED", { reason: "invalid_bot_token", token: "x" }),
    );
    expect(text).not.toContain("сообщение BFF");
  });

  it("признаки для интерфейса", () => {
    expect(isWrongPassword(error(422, "WRONG_PASSWORD"))).toBe(true);
    expect(isWrongPassword(error(423, "ACCOUNT_LOCKED"))).toBe(true);
    expect(isWrongPassword(error(422, "VALIDATION_FAILED"))).toBe(false);
    expect(isForbidden(error(403, "FORBIDDEN"))).toBe(true);
    expect(isForbidden(error(503, "BACKEND_UNAVAILABLE"))).toBe(false);
  });
});
