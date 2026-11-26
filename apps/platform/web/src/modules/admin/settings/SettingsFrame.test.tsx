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

/** Страницы группы — пункты под заголовком группы единого меню Настроек (НАСТ-1) */
const pages = (nav: HTMLElement, group: string) => {
  const list = within(nav).getByRole("group", { name: group });
  return within(list).getAllByRole("link");
};

describe("Настройки · рамка страницы (ЕВ-2а, отчёт §7 п. 20)", () => {
  it("все страницы — в одном меню по группам, открытая отмечена; второго меню нет", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/timing");
    const nav = await screen.findByRole("navigation", { name: "Разделы модуля" });
    expect(pages(nav, "Правила работы").map((link) => link.textContent)).toEqual([
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
    // одно меню: колонки страниц группы внутри страницы больше нет
    expect(screen.queryByRole("navigation", { name: /^Страницы/ })).toBeNull();
    expect(await screen.findByRole("heading", { level: 1, name: "Время и сроки" })).toBeVisible();
  });

  it("«Обмен между системами» — вид «Истории»: меню группы «Журнал», «История» подсвечена", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/bus");
    const nav = await screen.findByRole("navigation", { name: "Разделы модуля" });
    expect(pages(nav, "Журнал").map((link) => link.textContent)).toEqual(["История", "Выгрузки"]);
    expect(within(nav).getByRole("link", { name: "История" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(entryAt("/admin/bus")?.key).toBe("audit");
  });

  it("директор: в меню нет страниц фундамента — «Журнал» ему только «История»; остальные группы на месте", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/audit");
    await screen.findByRole("heading", { level: 1, name: "История" });
    const nav = await screen.findByRole("navigation", { name: "Разделы модуля" });
    expect(pages(nav, "Журнал").map((link) => link.textContent)).toEqual(["История"]);
    expect(within(nav).queryByRole("link", { name: "Выгрузки" })).toBeNull();
  });

  it("директор: «Правила работы» — Продажи, Время и сроки, Справочники, Шаблоны, Уведомления; коммерческие правит, остальное читает", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/sales");
    const nav = await screen.findByRole("navigation", { name: "Разделы модуля" });
    expect(pages(nav, "Правила работы").map((link) => link.textContent)).toEqual([
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

  it("телефон: одно меню — выпадающий список страниц над страницей, а не колонка слева", async () => {
    setViewportWidth(390);
    signInAs("admin@demo.example");
    renderApp("/admin/numbering");
    expect(await screen.findByRole("combobox", { name: "Страницы настроек" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: /^Страницы/ })).toBeNull();
  });
});
