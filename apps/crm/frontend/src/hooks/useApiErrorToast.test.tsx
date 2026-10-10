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
