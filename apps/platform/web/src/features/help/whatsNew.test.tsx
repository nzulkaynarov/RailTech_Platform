import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { resetFeedMocks } from "../../mocks/feedHandlers";
import { endSession, readSession, updateSession } from "../../mocks/mockSession";
import { readTickets, resetTicketsMock } from "../../mocks/ticketsStore";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { setViewportWidth } from "../../test/viewport";
import { CHANGELOG, LATEST_WHATS_NEW } from "./changelog";

// W-REL: окно «Платформа обновлена» один раз на сотрудника, отметка «Новое» у «?», «Что нового» снимает её; под статьёй —
// «Помогла?» и «Здесь устарело» (обращение администратору).
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

function signInWithNews(email = "manager@demo.example") {
  signInAs(email);
  updateSession({ whatsNewShown: null, whatsNewRead: null });
}

describe("«Платформа обновлена» (W-REL)", () => {
  it("после выкладки: окно в углу и отметка «Новое» у «?»; «Закрыть» убирает окно навсегда, отметка остаётся", async () => {
    signInWithNews();
    renderApp("/dashboard/queue");
    const notice = await screen.findByRole("region", { name: "Платформа обновлена" });
    // Окно называет последнюю запись — заголовок берём из неё, а не из конкретной даты.
    expect(
      within(notice).getByText(CHANGELOG[0]?.title ?? "", { exact: false }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Помощь (клавиша ?), есть новое" }),
    ).toBeInTheDocument();

    fireEvent.click(within(notice).getByRole("button", { name: "Закрыть" }));

    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Платформа обновлена" })).toBeNull();
    });
    await waitFor(() => {
      expect(readSession()?.whatsNewShown).toBe(LATEST_WHATS_NEW);
    });
    expect(readSession()?.whatsNewRead).toBeNull();
    expect(
      screen.getByRole("button", { name: "Помощь (клавиша ?), есть новое" }),
    ).toBeInTheDocument();

    // Новый вход (новое устройство): окно не возвращается — флаг на сервере, не в браузере.
    cleanup();
    window.localStorage.removeItem("rt-pf-mock-whats-new");
    renderApp("/dashboard/queue");
    await screen.findByRole("button", { name: "Помощь (клавиша ?), есть новое" });
    expect(screen.queryByRole("region", { name: "Платформа обновлена" })).toBeNull();
  });

  it("«Что нового» из окна открывает записи по датам с ролями и снимает отметку «Новое»", async () => {
    signInWithNews();
    renderApp("/dashboard/queue");
    const notice = await screen.findByRole("region", { name: "Платформа обновлена" });
    fireEvent.click(within(notice).getByRole("button", { name: "Что нового" }));

    expect(
      await screen.findByRole("heading", { name: "Помощь, профиль и первые рабочие экраны" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Директор").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Для всех").length).toBeGreaterThan(0);
    expect(await screen.findByRole("button", { name: "Помощь (клавиша ?)" })).toBeInTheDocument();
    await waitFor(() => {
      expect(readSession()?.whatsNewRead).toBe(LATEST_WHATS_NEW);
    });
    expect(readSession()?.whatsNewShown).toBe(LATEST_WHATS_NEW);
    expect(screen.queryByRole("region", { name: "Платформа обновлена" })).toBeNull();
  });

  it("всё видевшему окна и отметки нет; новичку окно не мешает приветствию", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    expect(await screen.findByRole("button", { name: "Помощь (клавиша ?)" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Платформа обновлена" })).toBeNull();
    cleanup();

    signInWithNews();
    updateSession({ onboardingDone: false });
    renderApp("/dashboard/queue");
    await screen.findByRole("dialog", { name: /Добро пожаловать/ });
    expect(screen.queryByRole("region", { name: "Платформа обновлена" })).toBeNull();
  });

  it("в окне помощи при новом — ссылка «Что нового»", async () => {
    signInWithNews();
    renderApp("/dashboard/queue");
    fireEvent.click(await screen.findByRole("button", { name: "Помощь (клавиша ?), есть новое" }));
    const help = await screen.findByRole("dialog", { name: "Помощь" });
    expect(within(help).getByRole("link", { name: "Что нового" })).toHaveAttribute(
      "href",
      "/help/news",
    );
  });
});

describe("Под статьёй: «Помогла?» и «Здесь устарело» (W-REL)", () => {
  it("«Да» — спасибо; «Нет» — предложение написать администратору", async () => {
    signInAs("manager@demo.example");
    renderApp("/help/articles/queue");
    const group = await screen.findByRole("group", { name: "Отзыв о статье" });
    fireEvent.click(within(group).getByRole("button", { name: "Да" }));
    expect(within(group).getByText("Спасибо! Рады, что помогло.")).toBeInTheDocument();
    cleanup();

    renderApp("/help/articles/queue");
    const again = await screen.findByRole("group", { name: "Отзыв о статье" });
    fireEvent.click(within(again).getByRole("button", { name: "Нет" }));
    fireEvent.click(within(again).getByRole("button", { name: "Написать администратору" }));
    const dialog = await screen.findByRole("dialog", { name: "Написать администратору" });
    expect(within(dialog).getByRole("textbox", { name: /Что случилось/ })).toHaveValue(
      "Статья помощи «Мои задачи — что сделать сейчас» не помогла: /help/articles/queue\nЧего не хватило: ",
    );
  });

  it("«Здесь устарело» создаёт обращение администратору с темой и ссылкой на статью", async () => {
    signInAs("manager@demo.example");
    renderApp("/help/articles/queue");
    const group = await screen.findByRole("group", { name: "Отзыв о статье" });
    fireEvent.click(within(group).getByRole("button", { name: "Здесь устарело" }));
    const dialog = await screen.findByRole("dialog", { name: "Написать администратору" });
    const body = within(dialog).getByRole("textbox", { name: /Что случилось/ });
    fireEvent.change(body, {
      target: {
        value:
          "Статья помощи «Мои задачи — что сделать сейчас» устарела: /help/articles/queue\nЧто изменилось: кнопка переехала",
      },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Отправить" }));

    expect(await screen.findByText(/Обращение ОБР-\d+ отправлено/)).toBeInTheDocument();
    const created = readTickets().tickets.at(-1);
    expect(created?.subject).toBe("other");
    expect(created?.body).toContain("/help/articles/queue");
    expect(created?.body).toContain("устарела");
  });
});
