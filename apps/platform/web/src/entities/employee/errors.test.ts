import i18n from "i18next";
import { describe, expect, it } from "vitest";

import { ApiError } from "../../shared/api/errors";
import "../../shared/i18n";
import { employeeErrorText } from "./errors";

const t = i18n.t.bind(i18n);

describe("employeeErrorText", () => {
  it("LAST_ADMIN — понятный текст про последнего администратора", () => {
    const error = new ApiError(409, "LAST_ADMIN", "x", "crm");
    expect(employeeErrorText(t, error)).toMatch(/последнего администратора/);
  });

  it("ROLES_REQUIRED (BFF 0.6.0) — хотя бы одна роль, закрыть доступ — отключить", () => {
    const error = new ApiError(422, "ROLES_REQUIRED", "x", "bff", { fields: ["role_ids"] });
    expect(employeeErrorText(t, error)).toBe(
      "Нужна хотя бы одна роль. Чтобы закрыть сотруднику доступ, отключите его.",
    );
  });

  it("EMAIL_EXISTS", () => {
    expect(employeeErrorText(t, new ApiError(409, "EMAIL_EXISTS", "x", "crm"))).toBe(
      "Сотрудник с такой почтой уже есть.",
    );
  });

  it("CONFLICT с лидами в работе (backend_code CRM) — отдельный текст", () => {
    const error = new ApiError(409, "CONFLICT", "x", "crm", {
      backend_code: "user_has_active_leads",
    });
    expect(employeeErrorText(t, error)).toMatch(/лиды в работе/);
  });

  it("прочий CONFLICT и не-ошибка API — общий текст", () => {
    expect(employeeErrorText(t, new ApiError(409, "CONFLICT", "x"))).toMatch(/Не удалось/);
    expect(employeeErrorText(t, new Error("boom"))).toMatch(/Не удалось/);
  });

  it("недоступность и права", () => {
    expect(employeeErrorText(t, new ApiError(503, "BACKEND_UNAVAILABLE", "x", "crm"))).toMatch(
      /CRM не отвечает/,
    );
    expect(employeeErrorText(t, new ApiError(403, "FORBIDDEN", "x"))).toMatch(/Недостаточно прав/);
  });
});
