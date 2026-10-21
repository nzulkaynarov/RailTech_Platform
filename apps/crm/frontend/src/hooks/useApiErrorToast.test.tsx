import { act, render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { describe, expect, it } from "vitest";

import { ApiError } from "../api/http";
import { apiErrorMessage, useApiErrorToast } from "./useApiErrorToast";

describe("apiErrorMessage", () => {
  it.each([
    [new ApiError(409, "last_admin", "raw"), "Нельзя снять роль с последнего администратора"],
    [new ApiError(400, "unknown_code", "Сервер объяснил"), "Сервер объяснил"],
    [new ApiError(500, "http_error", "HTTP 500"), "Что-то пошло не так"],
    [
      new ApiError(409, "conflict", "lead is already taken", {
        reason: "lead_taken",
        assigned_user_name: "Азиз",
      }),
      "Лида уже забрал Азиз — обновите страницу",
    ],
    [
      new ApiError(422, "validation_failed", "kb format", {
        reason: "kb_format",
        detail: "Нет заголовка первого уровня",
      }),
      "Документ не подходит под формат базы знаний: Нет заголовка первого уровня",
    ],
    [
      new ApiError(422, "validation_failed", "md only", { reason: "kb_markdown_only" }),
      "Принимаются только документы Markdown (.md) по формату базы знаний — см. «Формат документа» в окне загрузки",
    ],
    [
      new ApiError(409, "conflict", "lead is already taken", { reason: "lead_taken" }),
      "Лида уже забрал коллега — обновите страницу",
    ],
    [
      new ApiError(422, "validation_failed", "wrong", {
        reason: "wrong_password",
        field: "current_password",
      }),
      "Текущий пароль неверен",
    ],
    [
      new ApiError(422, "validation_failed", "x", { reason: "brand_new_reason" }),
      "Проверьте поля формы",
    ],
    [new TypeError("Failed to fetch"), "Что-то пошло не так"],
    [undefined, "Что-то пошло не так"],
  ])("%s → %s", (error, text) => {
    expect(apiErrorMessage(error)).toBe(text);
  });
});

function Trigger({ error }: { error: unknown }) {
  const onError = useApiErrorToast();
  return (
    <button
      type="button"
      onClick={() => {
        onError(error);
      }}
    >
      fail
    </button>
  );
}

describe("useApiErrorToast", () => {
  it("shows the mapped error as a toast", async () => {
    render(
      <AntApp>
        <Trigger error={new ApiError(403, "forbidden", "")} />
      </AntApp>,
    );
    act(() => {
      screen.getByRole("button").click();
    });
    expect(await screen.findByText("Недостаточно прав")).toBeInTheDocument();
  });
});
