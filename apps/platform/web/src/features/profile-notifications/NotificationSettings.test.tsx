import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { endSession } from "../../mocks/mockSession";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";
import { testErrorKey } from "./errors";
import { ApiError } from "../../shared/api/errors";

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

async function openProfile() {
  renderApp("/dashboard/queue");
  fireEvent.click(await screen.findByRole("button", { name: /профиль и настройки/i }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "Профиль" }));
  const dialog = await screen.findByRole("dialog", { name: "Профиль" });
  await within(dialog).findByRole("heading", { name: "Уведомления" });
  return dialog;
}

describe("Профиль → Уведомления", () => {
  it("менеджер с Telegram: подписка сохраняется, системных оповещений нет, тест отправляется", async () => {
    signInAs("manager@demo.example");
    const dialog = await openProfile();

    expect(await within(dialog).findByText("Привязан")).toBeInTheDocument();
    expect(within(dialog).queryByText("Системные оповещения")).toBeNull();
    const leads = within(dialog).getByRole("switch", { name: "Лиды, которые ждут меня" });
    expect(leads).toBeChecked();

    fireEvent.click(leads);
    await waitFor(() => {
      expect(
        within(dialog).getByRole("switch", { name: "Лиды, которые ждут меня" }),
      ).not.toBeChecked();
    });

    fireEvent.click(within(dialog).getByRole("button", { name: "Тестовое уведомление" }));
    expect(await screen.findByText("Тестовое сообщение отправлено в Telegram")).toBeInTheDocument();
  });

  it("администратору предлагаются системные оповещения", async () => {
    signInAs("admin@demo.example");
    const dialog = await openProfile();

    const system = await within(dialog).findByRole("switch", { name: "Системные оповещения" });
    expect(system).not.toBeChecked();
    fireEvent.click(system);
    await waitFor(() => {
      expect(within(dialog).getByRole("switch", { name: "Системные оповещения" })).toBeChecked();
    });
  });

  it("Telegram не привязан: подписки и тест недоступны, подсказка словами", async () => {
    signInAs("engineer@demo.example");
    const dialog = await openProfile();

    expect(await within(dialog).findByText("Не привязан")).toBeInTheDocument();
    expect(within(dialog).getByText(/Telegram привязывает администратор/)).toBeInTheDocument();
    expect(within(dialog).getByRole("switch", { name: "Лиды, которые ждут меня" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Тестовое уведомление" })).toBeDisabled();
  });

  it("доставка не удалась: предупреждение со временем; тест снимает его", async () => {
    signInAs("accountant@demo.example");
    const dialog = await openProfile();
    expect(
      await within(dialog).findByText(/Последнее сообщение бота не дошло/),
    ).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Тестовое уведомление" }));

    await waitFor(() => {
      expect(within(dialog).queryByText(/Последнее сообщение бота не дошло/)).toBeNull();
    });
  });

  it("Telegram отказал: понятная ошибка, не «что-то пошло не так»", async () => {
    server.use(
      http.post("*/me/test-notification", () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "x",
            source: "crm",
            details: { reason: "telegram_refused" },
          },
          { status: 409 },
        ),
      ),
    );
    signInAs("manager@demo.example");
    const dialog = await openProfile();

    fireEvent.click(await within(dialog).findByRole("button", { name: "Тестовое уведомление" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Telegram не принял сообщение",
    );
  });

  it("ключи ошибок тестового уведомления", () => {
    const err = (code: string, details: Record<string, unknown> = {}) =>
      new ApiError(409, code, "x", "crm", details);
    expect(testErrorKey(err("NOT_CONFIGURED"))).toBe("NOT_CONFIGURED");
    expect(testErrorKey(err("CONFLICT", { reason: "telegram_not_linked" }))).toBe("NOT_LINKED");
    expect(testErrorKey(err("CONFLICT", { reason: "telegram_refused" }))).toBe("REFUSED");
    expect(testErrorKey(err("BACKEND_UNAVAILABLE"))).toBe("BACKEND_UNAVAILABLE");
    expect(testErrorKey(new Error("x"))).toBe("DEFAULT");
  });
});
