import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { resetFeedMocks } from "../../mocks/feedHandlers";
import { endSession } from "../../mocks/mockSession";
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

/** Пункт открытого выпадающего списка antd по подписи. */
async function option(label: string): Promise<Element> {
  return waitFor(() => {
    const found = document.querySelector(`.ant-select-item-option[title="${label}"]`);
    expect(found).not.toBeNull();
    return found as Element;
  });
}

async function writeFromForbidden(text: string) {
  signInAs("manager@demo.example");
  renderApp("/admin/org");
  fireEvent.click(await screen.findByRole("button", { name: "Написать администратору" }));
  const dialog = await screen.findByRole("dialog", { name: "Написать администратору" });
  fireEvent.change(within(dialog).getByRole("textbox", { name: "Что случилось" }), {
    target: { value: text },
  });
  return dialog;
}

describe("Обращения к администратору", () => {
  it("«Нет доступа»: тема «Нужен доступ» выбрана, страница и роль приложены; пустой текст не уходит", async () => {
    signInAs("manager@demo.example");
    renderApp("/admin/org");
    fireEvent.click(await screen.findByRole("button", { name: "Написать администратору" }));
    const dialog = await screen.findByRole("dialog", { name: "Написать администратору" });
    expect(within(dialog).getByText("Нужен доступ к разделу")).toBeInTheDocument();
    expect(within(dialog).getByText(/страница \/admin\/org, роль Менеджер/)).toBeInTheDocument();
    expect(within(dialog).getByText("Что произойдёт")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Отправить" }));
    expect(await within(dialog).findByText("Опишите, что случилось")).toBeInTheDocument();
    expect(within(dialog).getByRole("textbox", { name: "Что случилось" })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("Escape закрывает окно без отправки", async () => {
    const dialog = await writeFromForbidden("Нужен доступ");
    fireEvent.keyDown(dialog, { key: "Escape", keyCode: 27 });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Написать администратору" })).toBeNull();
    });
    expect(window.localStorage.getItem("rt-pf-mock-tickets")).toBeNull();
  });

  it("путь целиком: сотрудник пишет, администратор видит и отвечает, сотрудник видит ответ в обращениях и колокольчике", async () => {
    // 1. Сотрудник пишет с экрана «Нет доступа».
    const dialog = await writeFromForbidden(
      "Нужен доступ к разделу «Оргструктура», чтобы приглашать",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Отправить" }));
    expect(await screen.findByText("Обращение ОБР-0001 отправлено")).toBeInTheDocument();
    cleanup();
    endSession();

    // 2. Администратор видит обращение в разделе и в колокольчике.
    signInAs("admin@demo.example");
    renderApp("/admin/tickets");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Обращения сотрудников" }),
    ).toBeInTheDocument();
    const row = await screen.findByRole("link", { name: "Открыть обращение ОБР-0001" });
    expect(row.closest("tr")).toHaveTextContent("Демо Менеджеров");
    expect(row.closest("tr")).toHaveTextContent("Новое");
    expect(screen.getByText(/Новых: 1/)).toBeInTheDocument();

    fireEvent.click(row);
    const panel = await screen.findByRole("heading", { level: 3, name: /ОБР-0001/ });
    const card = panel.parentElement as HTMLElement;
    expect(within(card).getByText(/Оргструктура/)).toBeInTheDocument();
    expect(within(card).getByText("/admin/org")).toBeInTheDocument();

    // 3. Ответ берёт обращение в работу.
    fireEvent.change(within(card).getByRole("textbox", { name: "Ваш ответ" }), {
      target: { value: "Доступ выдан, зайдите заново" },
    });
    fireEvent.click(within(card).getByRole("button", { name: "Отправить ответ" }));
    expect(await within(card).findByText("Ответ отправлен")).toBeInTheDocument();
    expect(within(card).getByText("Доступ выдан, зайдите заново")).toBeInTheDocument();
    await waitFor(() => {
      expect(row.closest("tr")).toHaveTextContent("В работе");
    });
    cleanup();
    endSession();

    // 4. Автор видит ответ в «Мои обращения» и в колокольчике; чужие обращения ему не видны.
    signInAs("manager@demo.example");
    renderApp("/help/requests/ОБР-0001");
    expect(await screen.findByText("Доступ выдан, зайдите заново")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /^Центр уведомлений/ }));
    const center = await screen.findByRole("dialog", { name: "Центр уведомлений" });
    expect(await within(center).findByText(/Ответ на обращение ОБР-0001/)).toBeInTheDocument();
  });

  it("статус меняется кнопкой: «Взять в работу» и «Отметить решённым»", async () => {
    const dialog = await writeFromForbidden("Не приходит уведомление о КП");
    fireEvent.click(within(dialog).getByRole("button", { name: "Отправить" }));
    await screen.findByText("Обращение ОБР-0001 отправлено");
    cleanup();
    endSession();

    signInAs("admin@demo.example");
    renderApp("/admin/tickets/ОБР-0001?panel=open&tab=card");
    const heading = await screen.findByRole("heading", { level: 3, name: /ОБР-0001/ });
    const card = heading.parentElement as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Взять в работу" }));
    expect(await within(card).findByText("Статус изменён")).toBeInTheDocument();
    fireEvent.click(await within(card).findByRole("button", { name: "Отметить решённым" }));
    await waitFor(() => {
      expect(within(card).getByRole("button", { name: "Вернуть в работу" })).toBeInTheDocument();
    });
  });

  it("новое обращение — строка в «Моих задачах» администратора и счётчик в меню; директору строки нет", async () => {
    const dialog = await writeFromForbidden("Нужен шаблон договора поставки");
    fireEvent.click(within(dialog).getByRole("button", { name: "Отправить" }));
    await screen.findByText("Обращение ОБР-0001 отправлено");
    cleanup();
    endSession();

    signInAs("admin@demo.example");
    renderApp("/dashboard/queue");
    const row = await screen.findByText("Ответить на обращение ОБР-0001");
    expect(row.closest("li")).toHaveTextContent("Демо Менеджеров");
    cleanup();
    endSession();

    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    await screen.findByRole("heading", { level: 1, name: "Мои задачи" });
    expect(screen.queryByText("Ответить на обращение ОБР-0001")).toBeNull();
  });

  it("пустой список — текст из задачи; фильтр без совпадений предлагает сбросить", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/tickets");
    expect(await screen.findByText("Обращений нет")).toBeInTheDocument();
    expect(
      screen.getByText("Сотрудники пишут сюда с экрана «Нет доступа» и из «Помощи»."),
    ).toBeInTheDocument();
  });

  it("директор читает обращения, но отвечать не может", async () => {
    const dialog = await writeFromForbidden("Ошибка при открытии письма");
    fireEvent.click(within(dialog).getByRole("button", { name: "Отправить" }));
    await screen.findByText("Обращение ОБР-0001 отправлено");
    cleanup();
    endSession();

    signInAs("director@demo.example");
    renderApp("/admin/tickets/ОБР-0001?panel=open&tab=card");
    const heading = await screen.findByRole("heading", { level: 3, name: /ОБР-0001/ });
    const card = heading.parentElement as HTMLElement;
    expect(within(card).queryByRole("textbox", { name: "Ваш ответ" })).toBeNull();
    expect(within(card).getByText(/Директор читает обращения/)).toBeInTheDocument();
  });

  it("сотрудник без доступа к Admin не открывает чужие обращения", async () => {
    signInAs("manager@demo.example");
    renderApp("/admin/tickets");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Нет доступа" }),
    ).toBeInTheDocument();
  });

  it("не больше пяти обращений в час: шестое — понятная ошибка, текст не теряется", async () => {
    signInAs("manager@demo.example");
    renderApp("/help/requests");
    for (let i = 1; i <= 6; i += 1) {
      fireEvent.click(
        (
          await screen.findAllByRole("button", { name: "Написать администратору" })
        )[0] as HTMLElement,
      );
      const dialog = await screen.findByRole("dialog", { name: "Написать администратору" });
      fireEvent.mouseDown(within(dialog).getByRole("combobox"));
      fireEvent.click(await option("Другое"));
      fireEvent.change(within(dialog).getByRole("textbox", { name: "Что случилось" }), {
        target: { value: `Вопрос номер ${String(i)}` },
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "Отправить" }));
      if (i < 6) {
        fireEvent.click(await screen.findByRole("button", { name: "Закрыть" }));
        await waitFor(() => {
          expect(screen.queryByRole("dialog", { name: /отправлено/ })).toBeNull();
        });
      } else {
        expect(await within(dialog).findByText(/слишком много обращений/)).toBeInTheDocument();
        expect(within(dialog).getByRole("textbox", { name: "Что случилось" })).toHaveValue(
          "Вопрос номер 6",
        );
      }
    }
  });
});
