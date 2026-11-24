import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, delay, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { endSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { server } from "../../../test/server";
import { panelEl } from "../../../test/botKit";
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
      http.get("*/staff", () =>
        HttpResponse.json({
          items: [
            {
              id: "7",
              name: "Анна Сотрудник",
              position: "Юрист",
              avatar_url: null,
              active: true,
              roles: ["Делопроизводитель"],
            },
          ],
        }),
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
    const leadCard = await panelEl();
    await within(leadCard).findByRole("heading", { level: 2, name: "Борис Лид" });
    // у лида контактов в списке нет — прочерк, а не «скоро»
    expect(within(leadCard).queryByRole("button", { name: /Показать/ })).toBeNull();
  });

  it("люди клиентов и партнёров (FR-11): компания и должность; телефон и почта — по нажатию", async () => {
    server.use(
      http.get("*/staff", () => HttpResponse.json({ items: [] })),
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
    const card = await panelEl();
    await within(card).findByRole("heading", { level: 2, name: "Демо Партнёров" });
    expect(within(card).getByText("ООО «Поставщик Север»")).toBeVisible();
    // в карточке одна кнопка «Показать контакты» на телефон и почту
    fireEvent.click(within(card).getByRole("button", { name: "Показать контакты" }));
    expect(await within(card).findByRole("link", { name: "partner@demo.example" })).toHaveAttribute(
      "href",
      "mailto:partner@demo.example",
    );
  });

  it("фото контакта (СУЩ-3): в строке — круг с фото, без фото — инициалы; адрес на BFF с версией", async () => {
    server.use(
      http.get("*/staff", () => HttpResponse.json({ items: [] })),
      http.get("*/crm/leads", () => HttpResponse.json({ items: [], total: 0 })),
      http.get("*/people/contacts", () =>
        HttpResponse.json({
          items: [
            {
              id: "41",
              name: "Демо Клиентов",
              position: null,
              has_email: false,
              has_phone: false,
              is_primary: true,
              company: { id: "7", name: "АО «Демо-Путь»" },
              kind: "client",
              photo_url: "/api/v1/people/contacts/41/photo?v=abc",
            },
            {
              id: "42",
              name: "Демо Партнёров",
              position: null,
              has_email: false,
              has_phone: false,
              is_primary: false,
              company: { id: "9", name: "ООО «Поставщик Север»" },
              kind: "partner",
              photo_url: null,
            },
          ],
          total: 2,
          page: 1,
          page_size: 100,
        }),
      ),
    );
    signInAs("all@demo.example");
    renderApp("/chats/contacts");

    const withPhoto = (await screen.findByRole("button", { name: "Демо Клиентов" })).closest(
      ".pf-entity",
    ) as HTMLElement;
    expect(withPhoto.querySelector("img")).toHaveAttribute(
      "src",
      "/api/v1/people/contacts/41/photo?v=abc",
    );
    const without = screen
      .getByRole("button", { name: "Демо Партнёров" })
      .closest(".pf-entity") as HTMLElement;
    expect(without.querySelector("img")).toBeNull();
    expect(without).toHaveTextContent("ДП");
  });

  it("список — в общей рамке: карточка, скелетон на загрузке, пустое состояние словами", async () => {
    server.use(
      http.get("*/staff", async () => {
        await delay(150);
        return HttpResponse.json({ items: [] });
      }),
      http.get("*/crm/leads", () => HttpResponse.json({ items: [], total: 0 })),
      http.get("*/people/contacts", () => HttpResponse.json({ items: [], total: 0 })),
    );
    signInAs("all@demo.example");
    renderApp("/chats/contacts");

    // пока грузится — скелетон внутри карточки, а не голый блок
    await screen.findByRole("heading", { level: 1, name: "Люди" });
    const frame = document.querySelector(".ant-card");
    expect(frame?.querySelector("[data-pf-skeleton]")).not.toBeNull();

    // нет людей — одна строка словами в той же рамке, без «Данные появятся здесь»
    expect(await screen.findByText("Никого не найдено")).toBeVisible();
    expect(frame?.contains(screen.getByText("Никого не найдено"))).toBe(true);
    expect(screen.queryByText("Данные появятся здесь")).toBeNull();
  });

  it("таблица в рамке карточки на общем DataTable; кнопок без действия («Написать», «Позвонить») нет", async () => {
    signInAs("all@demo.example");
    renderApp("/chats/contacts");

    fireEvent.click(await screen.findByRole("button", { name: "Демо Клиентов" }));
    const card = await panelEl();
    await within(card).findByRole("heading", { level: 2, name: "Демо Клиентов" });
    expect(within(card).queryByRole("button", { name: /Написать|Позвонить/ })).toBeNull();
    expect(document.querySelector(".ant-card table.pf-dt-table")).not.toBeNull();
  });

  it.each(["manager", "director", "supply", "engineer", "accountant", "registrar", "admin"])(
    "сотрудники видны любой роли с доступом к «Людям»: %s читает имя, должность и роли без контактов",
    async (who) => {
      server.use(
        http.get("*/staff", () =>
          HttpResponse.json({
            items: [
              {
                id: "7",
                name: "Анна Сотрудник",
                position: "Юрист",
                avatar_url: null,
                active: true,
                roles: ["Делопроизводитель"],
              },
              {
                id: "8",
                name: "Ушёл Давно",
                position: null,
                avatar_url: null,
                active: false,
                roles: [],
              },
            ],
          }),
        ),
        http.get("*/crm/leads", () => HttpResponse.json({ items: [], total: 0 })),
      );
      signInAs(`${who}@demo.example`);
      renderApp("/chats/contacts");

      fireEvent.click(await screen.findByRole("button", { name: "Анна Сотрудник" }));
      const card = await panelEl();
      expect(
        await within(card).findByRole("heading", { level: 2, name: "Анна Сотрудник" }),
      ).toBeVisible();
      // отключённого в «Людях» нет; в списке и в карточке телефона и почты до нажатия нет
      expect(screen.queryByRole("button", { name: "Ушёл Давно" })).toBeNull();
      expect(within(card).getByText("Делопроизводитель")).toBeVisible();
      expect(document.body.textContent).not.toMatch(/@demo\.example|\+99890/);
    },
  );

  it("карточка сотрудника: «Показать контакты» вызывает сервер один раз и показывает телефон и почту", async () => {
    let calls = 0;
    server.use(
      http.get("*/staff", () =>
        HttpResponse.json({
          items: [
            {
              id: "7",
              name: "Анна Сотрудник",
              position: "Юрист",
              avatar_url: null,
              active: true,
              roles: [],
            },
          ],
        }),
      ),
      http.get("*/crm/leads", () => HttpResponse.json({ items: [], total: 0 })),
      http.post("*/people/staff/:id/reveal", ({ params }) => {
        calls += 1;
        return HttpResponse.json({
          id: String(params["id"]),
          phone: "+998901234567",
          email: "anna@demo.example",
        });
      }),
    );
    signInAs("manager@demo.example");
    renderApp("/chats/contacts");

    fireEvent.click(await screen.findByRole("button", { name: "Анна Сотрудник" }));
    const heading = await screen.findByRole("heading", { level: 2, name: "Анна Сотрудник" });
    expect(calls).toBe(0);
    expect(screen.queryByText("anna@demo.example")).toBeNull();
    const card = heading.closest(".pf-people-card");
    if (!(card instanceof HTMLElement)) throw new Error("нет карточки");
    fireEvent.click(within(card).getByRole("button", { name: "Показать контакты" }));
    expect(await within(card).findByRole("link", { name: "anna@demo.example" })).toHaveAttribute(
      "href",
      "mailto:anna@demo.example",
    );
    expect(within(card).getByRole("link", { name: "+998901234567" })).toBeVisible();
    expect(calls).toBe(1);
    expect(within(card).queryByRole("button", { name: "Показать контакты" })).toBeNull();
  });

  it("журнал не принял показ — контактов нет, сказано словами", async () => {
    server.use(
      http.get("*/staff", () =>
        HttpResponse.json({
          items: [
            {
              id: "7",
              name: "Анна Сотрудник",
              position: null,
              avatar_url: null,
              active: true,
              roles: [],
            },
          ],
        }),
      ),
      http.get("*/crm/leads", () => HttpResponse.json({ items: [], total: 0 })),
      http.post("*/people/staff/:id/reveal", () =>
        HttpResponse.json({ code: "BACKEND_UNAVAILABLE", message: "x" }, { status: 503 }),
      ),
    );
    signInAs("manager@demo.example");
    renderApp("/chats/contacts");
    fireEvent.click(await screen.findByRole("button", { name: "Анна Сотрудник" }));
    fireEvent.click(await screen.findByRole("button", { name: "Показать контакты" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Контакты не показаны");
    expect(document.body.textContent).not.toMatch(/@demo\.example/);
  });

  it("выгрузки людей нет: ни CSV, ни Excel, ни «Экспорт»", async () => {
    signInAs("admin@demo.example");
    renderApp("/chats/contacts");
    await screen.findByRole("button", { name: "Демо Клиентов" });
    expect(screen.queryByRole("button", { name: /экспорт|выгруз|csv|excel/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /экспорт|выгруз|csv|excel/i })).toBeNull();
  });
});
