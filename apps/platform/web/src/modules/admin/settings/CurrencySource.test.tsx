import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { resetCompanyMock } from "../../../mocks/fixtures/company";
import { endSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { setViewportWidth } from "../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  resetCompanyMock();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  cleanup();
  endSession();
});

const PAGE = "/admin/dictionaries?list=currencies";

describe("Настройки · Справочники · Валюты: источник «ЦБ» (решение 2026-11-11)", () => {
  it("видны источник и дата; у строки — откуда она; «Обновить» ставит обновление в очередь", async () => {
    signInAs("admin@demo.example");
    renderApp(PAGE);
    expect(await screen.findByText(/^Источник: ЦБ · /)).toBeInTheDocument();
    const usd = (await screen.findByText("USD")).closest("tr") as HTMLElement;
    expect(within(usd).getByText(/^ЦБ · /)).toBeInTheDocument();
    const uzs = screen.getByText("UZS").closest("tr") as HTMLElement;
    expect(within(uzs).getByText("Вручную")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByText(/Обновление запущено/)).toBeInTheDocument();
  });

  it("директор правит валюты, но «Обновить» у него нет — только у администратора", async () => {
    signInAs("director@demo.example");
    renderApp(PAGE);
    expect(await screen.findByText(/^Источник: ЦБ · /)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Добавить значение" })).toBeEnabled();
    });
    expect(screen.queryByRole("button", { name: "Обновить" })).toBeNull();
    expect(screen.queryByText("Только просмотр")).toBeNull();
  });
});
