import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { endSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

describe("Органайзер · Люди", () => {
  it("общий список: сотрудники, лиды, люди клиентов и партнёров; фильтр, поиск и карточка", async () => {
    server.use(
      http.get("*/eds/staff", () =>
        HttpResponse.json({ items: [{ id: "7", name: "Анна Сотрудник", position: "Юрист" }] }),
      ),
      http.get("*/crm/leads", () =>
        HttpResponse.json({
          items: [
            {
              lead: "L-1001",
              name: "Борис Лид",
              status: "new",
              channel: "telegram",
              language: "ru",
              assigned: null,
              need: null,
              last_message_at: null,
              unread: false,
              handoff_open: false,
              overdue: false,
              client_id: null,
            },
          ],
          total: 1,
        }),
      ),
    );
    signInAs("all@demo.example");
    renderApp("/chats/contacts");

    expect(await screen.findByRole("button", { name: "Анна Сотрудник" })).toBeVisible();
    expect(await screen.findByRole("button", { name: "Борис Лид" })).toBeVisible();

    fireEvent.click(screen.getByText("Лиды", { selector: ".ant-segmented-item-label" }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Анна Сотрудник" })).toBeNull();
    });

    fireEvent.click(screen.getByRole("button", { name: "Борис Лид" }));
    const leadCard = await screen.findByRole("dialog", { name: "Борис Лид" });
    // у лида контактов в списке нет — прочерк, а не «скоро»
    expect(within(leadCard).queryByRole("button", { name: /Показать/ })).toBeNull();
  });

  it("люди клиентов и партнёров (FR-11): компания и должность; телефон и почта — по нажатию", async () => {
    server.use(
      http.get("*/eds/staff", () => HttpResponse.json({ items: [] })),
      http.get("*/crm/leads", () => HttpResponse.json({ items: [], total: 0 })),
    );
    signInAs("all@demo.example");
    renderApp("/chats/contacts");

    expect(await screen.findByRole("button", { name: "Демо Клиентов" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Демо Партнёров" })).toBeVisible();
    expect(screen.getByText("АО «Демо-Путь»")).toBeVisible();

    fireEvent.click(screen.getByText("Люди партнёров", { selector: ".ant-segmented-item-label" }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Демо Клиентов" })).toBeNull();
    });

    // контакты в списке не раскрыты — только по нажатию «Показать» (показ пишется в журнал)
    expect(screen.queryByText("partner@demo.example")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Демо Партнёров" }));
    const card = await screen.findByRole("dialog", { name: "Демо Партнёров" });
    expect(within(card).getByText("ООО «Поставщик Север»")).toBeVisible();
    fireEvent.click(
      within(card).getAllByRole("button", { name: "Показать телефон и почту: Демо Партнёров" })[0],
    );
    expect(await within(card).findByRole("link", { name: "partner@demo.example" })).toHaveAttribute(
      "href",
      "mailto:partner@demo.example",
    );
  });
});
