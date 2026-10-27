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

  it("стрелки и Enter: у объекта с экраном открывается его адрес из ответа BFF вместе с боковым окном", async () => {
    server.use(
      http.get("*/search", () =>
        HttpResponse.json({
          groups: [
            {
              module: "eds",
              items: [
                {
                  title: "Письмо ВХ-104/26",
                  subtitle: "ООО «Демо-Депо»",
                  object: {
                    kind: "letter",
                    number: "ВХ-104/26",
                    path: "/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution",
                  },
                },
              ],
            },
          ],
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
    );
    signInAs("director@demo.example");
    const { router } = renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "ВХ-104/26");
    await screen.findByRole("option", { name: /ВХ-104\/26/ });
    fireEvent.keyDown(box, { key: "ArrowDown" });
    expect(box).toHaveAttribute("aria-activedescendant");
    fireEvent.keyDown(box, { key: "Enter" });

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/inbox/%D0%92%D0%A5-104%2F26");
    });
    expect(router.state.location.search).toBe("?panel=open&tab=resolution");
    expect(box).toHaveValue("");
  });

  it("у объекта без экрана — «Где посмотреть» с мостом, а не заглушка: адрес не меняется, поиск остаётся открытым", async () => {
    signInAs("manager@demo.example");
    const { router } = renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "L-2041");
    fireEvent.click(await screen.findByRole("option", { name: /L-2041/ }));

    const where = await screen.findByRole("region", { name: "Где посмотреть" });
    expect(within(where).getByText(/Сейчас — в старой CRM: раздел «Лиды»/)).toBeInTheDocument();
    expect(
      await within(where).findByRole("link", { name: /Открыть в старой CRM/ }),
    ).toHaveAttribute("href", "http://crm.localhost:8088/leads/2041");
    expect(router.state.location.pathname).toBe("/dashboard/queue");
    expect(box).toHaveValue("L-2041");

    fireEvent.click(within(where).getByRole("button", { name: "Закрыть подсказку" }));
    expect(screen.queryByRole("region", { name: "Где посмотреть" })).toBeNull();
  });

  it("слова «создать заявку» добавляют группу «Действия»; без права на запись действия нет", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "создать заявку");
    const action = await screen.findByRole("option", { name: /Создать заявку/ });
    expect(within(action).getByText("Действие")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Действия" })).toBeInTheDocument();
    fireEvent.click(action);
    const where = await screen.findByRole("region", { name: /Где посмотреть/ });
    expect(within(where).getByText(/Сейчас — в старой CRM/)).toBeInTheDocument();

    type(box, "пригласить");
    await waitFor(() => {
      expect(screen.queryByRole("option", { name: /Пригласить сотрудника/ })).toBeNull();
    });
  });

  it("«Где посмотреть»: появляется в области aria-live, Escape внутри закрывает её и возвращает фокус в поле", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "L-2041");
    fireEvent.click(await screen.findByRole("option", { name: /L-2041/ }));

    const where = await screen.findByRole("region", { name: "Где посмотреть" });
    expect(where.parentElement).toHaveAttribute("aria-live", "polite");
    fireEvent.keyDown(where, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Где посмотреть" })).toBeNull();
    expect(box).toHaveFocus();
  });

  it("действия — после найденных объектов; Enter при одном объекте открывает объект, а не действие", async () => {
    server.use(
      http.get("*/search", () =>
        HttpResponse.json({
          groups: [
            {
              module: "eds",
              items: [
                {
                  title: "Письмо ВХ-104/26",
                  object: {
                    kind: "letter",
                    number: "ВХ-104/26",
                    path: "/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution",
                  },
                },
              ],
            },
          ],
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
    );
    signInAs("manager@demo.example");
    const { router } = renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "создать заявку");
    await screen.findByRole("option", { name: /Письмо ВХ-104\/26/ });
    const groups = screen.getAllByRole("group").map((g) => g.textContent);
    expect(groups.findIndex((g) => g.includes("Письмо"))).toBeLessThan(
      groups.findIndex((g) => g.includes("Создать заявку")),
    );

    fireEvent.keyDown(box, { key: "Enter" });

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/inbox/%D0%92%D0%A5-104%2F26");
    });
    expect(screen.queryByRole("region", { name: /Где посмотреть/ })).toBeNull();
  });

  it("действие без экрана подписано честно: «Пока делается в старой системе»", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "создать заявку");
    const action = await screen.findByRole("option", { name: /Создать заявку/ });
    expect(action).toHaveTextContent("Пока делается в старой системе");
    expect(action).not.toHaveTextContent(/фаз/i);
  });

  it("администратор: «пригласить» — действие, которое ведёт в Оргструктуру с приглашением", async () => {
    signInAs("admin@demo.example");
    const { router } = renderApp("/dashboard/queue");
    const box = await searchBox();

    type(box, "пригласить");
    fireEvent.click(await screen.findByRole("option", { name: /Пригласить сотрудника/ }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/admin/org");
    });
    expect(router.state.location.search).toBe("?invite=open&panel=open");
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
