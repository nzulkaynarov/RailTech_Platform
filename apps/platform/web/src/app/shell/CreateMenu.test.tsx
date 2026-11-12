import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { resetLeads } from "../../mocks/fixtures/leads";
import { renderApp, signInAs } from "../../test/renderApp";
import { setViewportWidth } from "../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  resetLeads();
  setViewportWidth(1440);
});

async function openCreate() {
  const rail = await screen.findByRole("navigation", { name: "Модули" });
  fireEvent.click(within(rail).getByRole("button", { name: "Создать" }));
  return screen.findByRole("dialog", { name: "Создать" });
}

describe("окно «Создать» (план 2026-11-12 п. 0.1)", () => {
  it("поиск сужает виды по названию, подписи и словам; нет совпадений — так и написано", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const dialog = await openCreate();
    fireEvent.change(within(dialog).getByRole("searchbox", { name: /Найти/ }), {
      target: { value: "служебка" },
    });
    expect(within(dialog).getByRole("link", { name: /^Внутренний документ/ })).toBeInTheDocument();
    expect(within(dialog).queryByRole("link", { name: /^Лид/ })).toBeNull();
    fireEvent.change(within(dialog).getByRole("searchbox", { name: /Найти/ }), {
      target: { value: "яблоко" },
    });
    expect(within(dialog).getByText("Ничего не найдено")).toBeInTheDocument();
  });

  it("«Часто у вас» — вид, открытый дважды", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    for (let i = 0; i < 2; i += 1) {
      const dialog = await openCreate();
      fireEvent.click(within(dialog).getByRole("link", { name: /^Исходящее письмо/ }));
      await waitFor(() => {
        expect(screen.queryByRole("dialog", { name: "Создать" })).toBeNull();
      });
    }
    const dialog = await openCreate();
    expect(within(dialog).getByText("Часто у вас")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Исходящее письмо" })).toHaveAttribute(
      "href",
      "/eds/new?type=letter",
    );
  });

  it("«Лид» открывает форму; лид создан — открывается его карточка; повтор контакта — ссылка на найденный", async () => {
    signInAs("manager@demo.example");
    const { router } = renderApp("/dashboard/queue");
    fireEvent.click(within(await openCreate()).getByRole("link", { name: /^Лид/ }));
    await screen.findByRole("form", { name: "Новый лид" });
    fireEvent.click(await screen.findByRole("button", { name: /Создать лид/ }));
    expect(await screen.findByText("Укажите имя")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "Азиз Каримов" } });
    fireEvent.click(await screen.findByRole("button", { name: /Создать лид/ }));
    expect(await screen.findByText("Укажите телефон")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Телефон"), {
      target: { value: "+998 90 555 11 22" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /Создать лид/ }));
    await waitFor(() => {
      expect(new URLSearchParams(router.state.location.search).get("lead")).toMatch(/^L-\d{4}$/);
    });
    const created = new URLSearchParams(router.state.location.search).get("lead") ?? "";

    void router.navigate("/crm/leads?new=1&panel=open&tab=card");
    await screen.findByRole("form", { name: "Новый лид" });
    fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "Ещё раз" } });
    fireEvent.change(screen.getByLabelText("Телефон"), {
      target: { value: "+998905551122" },
    });
    fireEvent.click(await screen.findByRole("button", { name: /Создать лид/ }));
    expect(await screen.findByRole("link", { name: created })).toHaveAttribute(
      "href",
      `/crm/leads?lead=${created}&panel=open&tab=card`,
    );
  });

  it("«Заявка» открывает форму с выбором клиента", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    fireEvent.click(within(await openCreate()).getByRole("link", { name: /^Заявка/ }));
    expect(await screen.findByRole("form", { name: "Создать заявку" })).toBeInTheDocument();
  });
});
