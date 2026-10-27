import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { endSession } from "../../mocks/mockSession";
import i18n from "../../shared/i18n";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

async function searchBox() {
  return screen.findByRole("combobox", { name: "Глобальный поиск" });
}

function type(box: HTMLElement, value: string) {
  fireEvent.focus(box);
  fireEvent.change(box, { target: { value } });
}

describe("Глобальный поиск", () => {
  it("находит сделку по номеру; результаты — группой модуля с названием вида объекта", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "ЗВ-2026-104");

    const list = await screen.findByRole("listbox", { name: "Результаты поиска" });
    const group = within(list).getByRole("group", { name: "Клиенты" });
    const option = within(group).getByRole("option", { name: /ЗВ-2026-104 · Стрелочные приводы/ });
    expect(option).toHaveTextContent("Заявка");
    expect(box).toHaveAttribute("aria-expanded", "true");
  });

  it("группы по модулям: CRM и EDS; роль видит только свои разделы", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "Демо");
    const list = await screen.findByRole("listbox", { name: "Результаты поиска" });
    expect(within(list).getByRole("group", { name: "Клиенты" })).toBeVisible();
    expect(within(list).getByRole("group", { name: "Документы" })).toBeVisible();
  });

  it("администратору матрица не открывает ни CRM, ни EDS: находить нечего", async () => {
    signInAs("admin@demo.example");
    renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "Демо");

    expect(await screen.findByText("По запросу «Демо» ничего не найдено.")).toBeInTheDocument();
    expect(screen.queryByRole("option")).toBeNull();
  });

  it("стрелки и Enter открывают объект по пути из ответа BFF", async () => {
    signInAs("manager@demo.example");
    const { router } = renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "СЧ-2026/142");
    await screen.findByRole("option", { name: /СЧ-2026\/142/ });
    fireEvent.keyDown(box, { key: "ArrowDown" });
    expect(box).toHaveAttribute("aria-activedescendant");
    fireEvent.keyDown(box, { key: "Enter" });

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/payments/%D0%A1%D0%A7-2026%2F142");
    });
    expect(router.state.location.search).toBe("?panel=open&tab=payment");
    expect(box).toHaveValue("");
  });

  it("клик по результату открывает объект", async () => {
    signInAs("manager@demo.example");
    const { router } = renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "L-2041");
    fireEvent.click(await screen.findByRole("option", { name: /L-2041/ }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/crm/leads");
    });
    expect(router.state.location.search).toBe("?lead=L-2041&panel=open&tab=card");
  });

  it("меньше двух символов — подсказка, запрос не уходит", async () => {
    let requests = 0;
    server.use(
      http.get("*/search", () => {
        requests += 1;
        return HttpResponse.json({ groups: [], sources: { crm: "ok", erp: "ok" } });
      }),
    );
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "з");

    expect(await screen.findByText("Введите не меньше двух символов.")).toBeVisible();
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(requests).toBe(0);
  });

  it("ничего не найдено — слова и запрос в кавычках", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "нет-такого-номера");

    expect(
      await screen.findByText("По запросу «нет-такого-номера» ничего не найдено."),
    ).toBeVisible();
  });

  it("ERP не отвечает: показано, что нашла CRM, и плашка «ERP не отвечает»", async () => {
    server.use(
      http.get("*/search", () =>
        HttpResponse.json({
          groups: [
            {
              module: "crm",
              items: [
                {
                  object: {
                    kind: "lead",
                    number: "L-2041",
                    path: "/crm/leads?lead=L-2041&panel=open&tab=card",
                  },
                  title: "ООО «Демо-Депо»",
                },
              ],
            },
          ],
          sources: { crm: "ok", erp: "unavailable" },
        }),
      ),
    );
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "депо");

    expect(await screen.findByRole("option", { name: /ООО «Демо-Депо»/ })).toBeVisible();
    expect(screen.getAllByRole("status").some((s) => /ERP не отвечает/.test(s.textContent))).toBe(
      true,
    );
  });

  it("Escape закрывает список, второй Escape очищает поле", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const box = await searchBox();
    type(box, "ЗВ-2026");
    await screen.findByRole("option", { name: /ЗВ-2026-104/ });

    fireEvent.keyDown(box, { key: "Escape" });
    expect(box).toHaveAttribute("aria-expanded", "false");
    fireEvent.keyDown(box, { key: "Escape" });
    expect(box).toHaveValue("");
  });
});
