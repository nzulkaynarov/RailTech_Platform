import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { resetFeedMocks } from "../../../mocks/feedHandlers";
import { resetLegalMock } from "../../../mocks/legalHandlers";
import { endSession } from "../../../mocks/mockSession";
import { resetTicketsMock } from "../../../mocks/ticketsStore";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { setViewportWidth } from "../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
  resetFeedMocks();
  resetTicketsMock();
  resetLegalMock();
});
afterEach(() => {
  cleanup();
  endSession();
});

const heading = () => screen.findByRole("heading", { level: 1, name: "Оферта и политика" });

describe("Настройки · Оферта и политика (ДВ-5)", () => {
  it("директор видит действующую политику, черновик условий и журнал принятий", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/legal");
    expect(await heading()).toBeInTheDocument();
    const privacy = (
      await screen.findByRole("heading", { name: "Политика обработки персональных данных" })
    ).closest(".ant-card") as HTMLElement;
    expect(privacy).toHaveTextContent("Действует: редакция от");
    expect(privacy).toHaveTextContent("Приняли: 3");
    const terms = screen
      .getByRole("heading", { name: "Условия использования (оферта)", level: 2 })
      .closest(".ant-card") as HTMLElement;
    expect(terms).toHaveTextContent("Не опубликована");
    expect(terms).toHaveTextContent("Черновик «2026-11-23»");
    expect(await screen.findByText(/Всего принятий: 4/)).toBeInTheDocument();
    // в журнале — кто, когда, какая редакция и язык
    const log = await screen.findByRole("table", { name: "Журнал принятий" });
    expect(within(log).getAllByText(/Азамат Каримов/).length).toBeGreaterThan(0);
  });

  it("публикация называет последствие и заменяет прежнюю редакцию; опубликованное не правится", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/legal");
    await heading();
    const terms = (
      await screen.findByRole("heading", { name: "Условия использования (оферта)", level: 2 })
    ).closest(".ant-card") as HTMLElement;

    fireEvent.click(within(terms).getByRole("button", { name: "Опубликовать" }));
    const dialog = await screen.findByRole("dialog", {
      name: /Опубликовать редакцию «2026-11-23»/,
    });
    expect(dialog).toHaveTextContent(
      "Все контакты кабинета примут новую редакцию при следующем входе",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Опубликовать" }));

    await waitFor(() => {
      expect(terms).toHaveTextContent("Действует: редакция от");
    });
    expect(screen.getByText("Редакция «2026-11-23» опубликована.")).toBeInTheDocument();
    // у опубликованной нет «Править черновик»; можно создать новую редакцию — копию действующей
    expect(within(terms).queryByRole("button", { name: "Править черновик" })).toBeNull();
    fireEvent.click(within(terms).getByRole("button", { name: "Новая редакция" }));
    expect(
      await screen.findByRole("heading", { name: /Черновик: Условия использования/ }),
    ).toBeInTheDocument();
  });

  it("черновик правится по языкам: раздел добавляется на все языки, сохранение отправляет три языка", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/legal");
    await heading();
    const terms = (
      await screen.findByRole("heading", { name: "Условия использования (оферта)", level: 2 })
    ).closest(".ant-card") as HTMLElement;
    fireEvent.click(within(terms).getByRole("button", { name: "Править черновик" }));

    const title = await screen.findByRole("textbox", { name: "Название документа" });
    expect(title).toHaveValue("Условия использования Кабинета (оферта)");
    fireEvent.change(title, { target: { value: "Условия (новая редакция)" } });
    fireEvent.click(screen.getByRole("radio", { name: "English" }));
    expect(await screen.findByRole("textbox", { name: "Название документа" })).toHaveValue(
      "Cabinet terms of use (offer)",
    );
    // подстановки показаны как текст, а не как пустота
    expect(screen.getByText(/\{\{company\.name\}\}.*\{\{company\.phone\}\}/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Добавить раздел" }));
    expect(await screen.findByText("Раздел 5")).toBeInTheDocument();
    // раздел пуст на всех языках — сервер не примет: ошибка словами
    fireEvent.click(await screen.findByRole("button", { name: "Сохранить черновик" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("на всех трёх языках");
  });

  it("менеджеру раздела нет", async () => {
    signInAs("manager@demo.example");
    renderApp("/admin/legal");
    await waitFor(() => {
      expect(screen.queryByRole("heading", { level: 1, name: "Оферта и политика" })).toBeNull();
    });
  });
});
