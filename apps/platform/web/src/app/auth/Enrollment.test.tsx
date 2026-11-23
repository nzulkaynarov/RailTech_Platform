import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { endSession } from "../../mocks/mockSession";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";

// ДВ-4б: сценарий моков «фактор обязателен» включается ключом до входа; остальные тесты входят по паролю как прежде
const REQUIRED = "rt-pf-mock-2fa-required";

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem(REQUIRED, "1");
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
  window.localStorage.clear();
});

async function signInWithPassword(email: string) {
  fireEvent.change(await screen.findByLabelText("Электронная почта"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "demo-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Войти" }));
}

describe("обязательный второй фактор при входе (ДВ-4б)", () => {
  it("бухгалтер без фактора после пароля попадает на настройку, а не в приложение", async () => {
    renderApp("/login");
    await signInWithPassword("accountant@demo.example");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Настройте вход с кодом" }),
    ).toBeVisible();
    expect(await screen.findByRole("img", { name: /QR-код/ })).toBeVisible();
    // сессии нет: приложение не открылось
    expect(screen.queryByRole("heading", { level: 1, name: "Задачи" })).toBeNull();
  });

  it("неверный код — ошибка, верный — резервные коды, и только «Я сохранил коды» открывает приложение", async () => {
    renderApp("/login");
    await signInWithPassword("accountant@demo.example");
    const code = await screen.findByLabelText("Код из приложения");

    fireEvent.change(code, { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Неверный код");

    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    expect(await screen.findByText(/Сохраните резервные коды/)).toBeVisible();
    expect(screen.getByText("4F7K-92QD")).toBeVisible();
    expect(screen.queryByRole("heading", { level: 1, name: "Задачи" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Я сохранил коды" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Задачи" })).toBeVisible();
  });

  it("менеджеру фактор не нужен: вход по паролю как прежде", async () => {
    renderApp("/login");
    await signInWithPassword("manager@demo.example");
    expect(await screen.findByRole("heading", { level: 1, name: "Задачи" })).toBeVisible();
  });

  it("после настройки следующий вход спрашивает код, а не настройку", async () => {
    window.localStorage.setItem(
      "rt-pf-mock-2fa",
      JSON.stringify({
        "u-demo-accountant": {
          enabled: true,
          enabledAt: "2026-11-23T09:00:00Z",
          backup: [],
          remembered: false,
        },
      }),
    );
    renderApp("/login");
    await signInWithPassword("accountant@demo.example");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Код из приложения" }),
    ).toBeVisible();
  });
});

describe("профиль держателя обязательного фактора", () => {
  it("фактор включён и обязателен: «Отключить» нет, сказано почему", async () => {
    window.localStorage.setItem(
      "rt-pf-mock-2fa",
      JSON.stringify({
        "u-demo-accountant": {
          enabled: true,
          enabledAt: "2026-11-23T09:00:00Z",
          backup: ["A"],
          remembered: true,
        },
      }),
    );
    signInAs("accountant@demo.example");
    renderApp("/me");
    await screen.findByRole("heading", { level: 1, name: "Профиль" });
    await waitFor(() => {
      expect(screen.getByText(/для вашего доступа код обязателен/i)).toBeVisible();
    });
    expect(screen.queryByRole("button", { name: "Отключить" })).toBeNull();
  });

  it("фактор не обязателен менеджеру: «Отключить» есть", async () => {
    window.localStorage.setItem(
      "rt-pf-mock-2fa",
      JSON.stringify({
        "u-demo-manager": {
          enabled: true,
          enabledAt: "2026-11-23T09:00:00Z",
          backup: ["A"],
          remembered: true,
        },
      }),
    );
    signInAs("manager@demo.example");
    renderApp("/me");
    await screen.findByRole("heading", { level: 1, name: "Профиль" });
    expect(await screen.findByRole("button", { name: "Отключить" })).toBeVisible();
  });
});
