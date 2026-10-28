import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { resetFeedMocks } from "../../mocks/feedHandlers";
import { endSession, updateSession } from "../../mocks/mockSession";
import { resetTicketsMock } from "../../mocks/ticketsStore";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { setViewportWidth } from "../../test/viewport";

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

async function openHelp() {
  fireEvent.click(await screen.findByRole("button", { name: "Помощь (клавиша ?)" }));
  return screen.findByRole("dialog", { name: "Помощь" });
}

describe("Окно помощи", () => {
  it("«?» рядом с колокольчиком открывает статью текущего раздела", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const help = await openHelp();
    expect(
      await within(help).findByRole("heading", { name: "Мои задачи — что сделать сейчас" }),
    ).toBeInTheDocument();
    expect(within(help).getByRole("link", { name: "Все статьи" })).toHaveAttribute(
      "href",
      "/help/articles",
    );
    expect(within(help).getByRole("button", { name: "Написать администратору" })).toBeEnabled();
  });

  it("поиск находит статью по слову; нет совпадений — подсказка и «Написать администратору»", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const help = await openHelp();
    const search = within(help).getByRole("textbox", { name: "Поиск по статьям" });
    fireEvent.change(search, { target: { value: "резолюция" } });
    expect(await within(help).findByText(/Найдено статей: \d+/)).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "ъъъъъ" } });
    expect(await within(help).findByText(/статей нет/)).toBeInTheDocument();
  });

  it("клавиша ? открывает окно, но не в поле ввода; Escape закрывает", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    await screen.findByRole("button", { name: "Помощь (клавиша ?)" });
    const search = await screen
      .findByRole("combobox", { name: /Глобальный поиск/ })
      .catch(() => null);
    if (search) {
      fireEvent.keyDown(search, { key: "?" });
      expect(screen.queryByRole("dialog", { name: "Помощь" })).toBeNull();
    }
    fireEvent.keyDown(document.body, { key: "?" });
    const help = await screen.findByRole("dialog", { name: "Помощь" });
    expect(help).toBeInTheDocument();
    fireEvent.keyDown(help, { key: "Escape", keyCode: 27 });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Помощь" })).toBeNull();
    });
  });

  it("пункт «Помощь» в меню аватара", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    fireEvent.click(await screen.findByRole("button", { name: /профиль и настройки/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Помощь" }));
    expect(await screen.findByRole("dialog", { name: "Помощь" })).toBeInTheDocument();
  });
});

describe("Раздел /help", () => {
  it("«С чего начать» по разделам каталога: бухгалтеру — платёжки, не шаги директора первыми", async () => {
    signInAs("accountant@demo.example");
    renderApp("/help");
    expect(await screen.findByRole("heading", { level: 1, name: "Помощь" })).toBeInTheDocument();
    expect(await screen.findByText(/Ваша роль: Бухгалтер/)).toBeInTheDocument();
    expect(screen.getByText(/Подтвердите оплату по выписке/)).toBeInTheDocument();
    expect(screen.getByText("Для других ролей")).toBeInTheDocument();
    expect(document.title).toContain("Помощь");
  });

  it("путь заявки — семь шагов; словарь, горячие клавиши и «Что нового» открываются по адресу", async () => {
    signInAs("manager@demo.example");
    renderApp("/help/path");
    const steps = await screen.findAllByRole("listitem");
    expect(steps.some((item) => item.textContent.startsWith("Резолюция"))).toBe(true);
    expect(screen.getByText("Выполнено")).toBeInTheDocument();
    cleanup();
    renderApp("/help/glossary");
    expect(await screen.findByText("Входящее письмо (ВХ-104/26)")).toBeInTheDocument();
    expect(screen.getByText("Служебная записка (СЗ-2026/031)")).toBeInTheDocument();
    cleanup();
    renderApp("/help/keys");
    expect(await screen.findByText("Ctrl K или ⌘ K")).toBeInTheDocument();
    cleanup();
    renderApp("/help/news");
    expect(
      await screen.findByRole("heading", { name: "Помощь, профиль и первые рабочие экраны" }),
    ).toBeInTheDocument();
  });

  it("статья по адресу; неизвестная статья — понятное сообщение", async () => {
    signInAs("manager@demo.example");
    renderApp("/help/articles/queue");
    expect(
      await screen.findByRole("heading", { name: "Мои задачи — что сделать сейчас" }),
    ).toBeInTheDocument();
    cleanup();
    renderApp("/help/articles/net-takoj");
    expect(await screen.findByText("Такой статьи нет")).toBeInTheDocument();
  });

  it("интерфейс на узбекском и английском: вкладки переведены, статьи честно помечены русскими", async () => {
    signInAs("manager@demo.example");
    updateSession({ language: "en" });
    renderApp("/help/articles/queue");
    expect(await screen.findByRole("link", { name: "Where to start" })).toBeInTheDocument();
    expect(screen.getByText("Articles are written in Russian for now.")).toBeInTheDocument();
    cleanup();
    updateSession({ language: "uz" });
    renderApp("/help/articles/queue");
    expect(await screen.findByRole("link", { name: "Nimadan boshlash" })).toBeInTheDocument();
  });
});
