import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { resetFeedMocks } from "../../../mocks/feedHandlers";
import { endSession } from "../../../mocks/mockSession";
import { resetTicketsMock } from "../../../mocks/ticketsStore";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { setViewportWidth } from "../../../test/viewport";
import { entryAt } from "../settingsRegistry";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
  resetFeedMocks();
  resetTicketsMock();
});
afterEach(() => {
  cleanup();
  endSession();
});

const names = (nav: HTMLElement) =>
  within(nav)
    .getAllByRole("link")
    .map((link) => link.textContent);

describe("Настройки · рамка страницы (ЕВ-2а, отчёт §7 п. 20)", () => {
  it("меню слева — страницы своей группы; текущая отмечена; те же страницы на любой странице группы", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/timing");
    const nav = await screen.findByRole("navigation", { name: "Страницы группы «Правила работы»" });
    expect(names(nav)).toEqual([
      "Продажи",
      "Время и сроки",
      "Справочники",
      "Шаблоны",
      "Уведомления",
    ]);
    expect(within(nav).getByRole("link", { name: "Время и сроки" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByRole("heading", { level: 1, name: "Время и сроки" })).toBeVisible();
  });

  it("«Обмен между системами» — вид «Истории»: меню группы «Журнал», «История» подсвечена", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/bus");
    const nav = await screen.findByRole("navigation", { name: "Страницы группы «Журнал»" });
    expect(names(nav)).toEqual(["История", "Выгрузки"]);
    expect(within(nav).getByRole("link", { name: "История" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(entryAt("/admin/bus")?.key).toBe("audit");
  });

  it("директор: в меню группы нет страниц фундамента — «Журнал» ему только «История», меню из одного пункта не рисуется", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/audit");
    await screen.findByRole("heading", { level: 1, name: "История" });
    expect(screen.queryByRole("navigation", { name: /^Страницы группы/ })).toBeNull();
  });

  it("директор: «Правила работы» — Продажи, Время и сроки, Справочники, Шаблоны, Уведомления; коммерческие правит, остальное читает", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/sales");
    const nav = await screen.findByRole("navigation", { name: "Страницы группы «Правила работы»" });
    expect(names(nav)).toEqual([
      "Продажи",
      "Время и сроки",
      "Справочники",
      "Шаблоны",
      "Уведомления",
    ]);
    // «Продажи» — раздел `company.settings`, директор правит: плашки «Только просмотр» нет
    await screen.findByRole("heading", { level: 1, name: "Продажи" });
    expect(screen.queryByText("Только просмотр")).toBeNull();
  });

  it("телефон: меню группы — выпадающий список над страницей, а не колонка слева", async () => {
    setViewportWidth(390);
    signInAs("admin@demo.example");
    renderApp("/admin/numbering");
    expect(
      await screen.findByRole("combobox", { name: /Страницы группы «Компания»/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: /^Страницы группы/ })).toBeNull();
  });
});
