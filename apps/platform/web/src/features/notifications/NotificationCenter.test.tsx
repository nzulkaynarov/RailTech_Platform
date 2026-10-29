import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../app/shell/panelsStore";
import { resetFeedMocks } from "../../mocks/feedHandlers";
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
  resetFeedMocks();
});
afterEach(() => {
  endSession();
});

async function openBell(name = /^Центр уведомлений/) {
  const bell = await screen.findByRole("button", { name });
  fireEvent.click(bell);
  return screen.findByRole("dialog", { name: "Центр уведомлений" });
}

/** Пункт открытого выпадающего списка antd по подписи. */
async function option(label: string): Promise<Element> {
  return waitFor(() => {
    const found = document.querySelector(`.ant-select-item-option[title="${label}"]`);
    expect(found).not.toBeNull();
    return found as Element;
  });
}

describe("Центр уведомлений", () => {
  it("колокольчик показывает число непрочитанных, окно — фильтры и список", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");

    expect(
      await screen.findByRole("button", { name: "Центр уведомлений, 3 новых" }),
    ).toBeInTheDocument();
    const center = await openBell(/^Центр уведомлений, 3 новых/);

    expect(within(center).getByText("Непрочитанные (3)")).toBeInTheDocument();
    expect(within(center).getByText("Все")).toBeInTheDocument();

    const list = await within(center).findByRole("list", { name: "Уведомления" });
    // По умолчанию выбран сегмент «Непрочитанные» -> 3 элемента
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);

    // Переключение на «Все» отображает все 7 уведомлений прямо в шторке
    fireEvent.click(within(center).getByText("Все"));
    expect(within(list).getAllByRole("listitem")).toHaveLength(7);

    // непрочитанное помечено словом, не только цветом; у договора и счёта есть экраны (D2-4, D2-5): ссылки, а не «Где посмотреть»
    expect(within(list).queryAllByRole("button", { name: /Где посмотреть/ })).toHaveLength(0);
    const first = within(list).getByRole("link", { name: /ДОГ-2026\/091/ });
    expect(first).toHaveTextContent("Новое: Клиент согласовал проект договора ДОГ-2026/091");
    expect(first).toHaveAttribute("href", expect.stringContaining("/eds/projects/"));
  });

  it("фильтр «Клиенты» оставляет только свои уведомления", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const center = await openBell();

    fireEvent.click(within(center).getByText("Все"));
    fireEvent.mouseDown(within(center).getByRole("combobox"));
    fireEvent.click(await option("Клиенты"));

    const list = await within(center).findByRole("list", { name: "Уведомления" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).queryByText(/КП-2026\/118 ждёт/)).toBeNull();
  });

  it("клик по уведомлению об объекте с экраном: отмечает прочитанным и открывает объект с боковым окном", async () => {
    server.use(
      http.get("*/notifications", () =>
        HttpResponse.json({
          items: [
            {
              id: "eds:letter:1",
              tab: "decisions",
              title: "Письмо ВХ-104/26 ждёт резолюции",
              created_at: new Date().toISOString(),
              read: false,
              object: {
                kind: "letter",
                number: "ВХ-104/26",
                path: "/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution",
              },
            },
          ],
          next_cursor: null,
          unread_count: 1,
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
    );
    signInAs("director@demo.example");
    const { router } = renderApp("/dashboard/queue");
    const center = await openBell();
    const requests: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.method === "POST") requests.push(new URL(request.url).pathname);
    });

    fireEvent.click(await within(center).findByRole("link", { name: /Письмо ВХ-104\/26 ждёт/ }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/inbox/%D0%92%D0%A5-104%2F26");
    });
    expect(router.state.location.search).toBe("?panel=open&tab=resolution");
    await waitFor(() => {
      expect(requests).toContain("/api/v1/notifications/eds:letter:1/read");
    });
    server.events.removeAllListeners();
  });

  it.each([
    [
      "director@demo.example",
      /Письмо ВХ-104\/26 ждёт резолюции/,
      "/eds/inbox/%D0%92%D0%A5-104%2F26",
      "?panel=open&tab=resolution",
    ],
    [
      "director@demo.example",
      /КП-2026\/118 ждёт вашего согласования/,
      "/eds/drafts/%D0%9A%D0%9F-2026%2F118",
      "?panel=open&tab=approve",
    ],
    [
      "director@demo.example",
      /СЗ-2026\/031 на согласовании/,
      "/eds/approvals/%D0%A1%D0%97-2026%2F031",
      "?panel=open&tab=agree",
    ],
    ["manager@demo.example", /Лид L-2041 просит КП/, "/crm/messages", "?lead=L-2041"],
  ])(
    "%s: «%s» открывает объект и вкладку решения, без «Где посмотреть» (D1-6)",
    async (email, title, pathname, search) => {
      signInAs(email);
      const { router } = renderApp("/dashboard/queue");
      const center = await openBell();

      fireEvent.click(within(center).getByText("Все"));

      expect(
        within(center).queryByRole("button", {
          name: /^Где посмотреть: .*(ВХ-104|КП-2026\/118|СЗ-2026|L-2041)/,
        }),
      ).toBeNull();
      fireEvent.click(await within(center).findByRole("link", { name: title }));

      await waitFor(() => {
        expect(router.state.location.pathname).toBe(pathname);
      });
      expect(router.state.location.search).toBe(search);
    },
  );

  it("уведомление об объекте без экрана: не заглушка, а «Где посмотреть» с мостом; окно остаётся открытым, прочитано", async () => {
    // раздел без экрана (исходящие КП ещё в старом ERP): у договоров и счетов экраны уже есть, берём КП из «Исходящих»
    server.use(
      http.get("*/notifications", () =>
        HttpResponse.json({
          items: [
            {
              id: "erp:90",
              tab: "decisions",
              title: "КП-2026/118 отправлено клиенту",
              created_at: new Date().toISOString(),
              read: false,
              object: {
                kind: "quote",
                number: "КП-2026/118",
                path: "/eds/outbox/%D0%9A%D0%9F-2026%2F118?panel=open&tab=card",
              },
            },
          ],
          next_cursor: null,
          unread_count: 1,
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
    );
    signInAs("director@demo.example");
    const { router } = renderApp("/dashboard/queue");
    const center = await openBell();
    const requests: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.method === "POST") requests.push(new URL(request.url).pathname);
    });

    const item = await within(center).findByRole("button", {
      name: /Где посмотреть.*КП-2026\/118/,
    });
    fireEvent.click(item);

    expect(item).toHaveAttribute("aria-expanded", "true");
    const where = within(center).getByRole("region", { name: "Где посмотреть" });
    expect(within(where).getByText(/Сейчас — в старом ERP/)).toBeInTheDocument();
    expect(
      await within(where).findByRole("link", { name: /Открыть в старом ERP/ }),
    ).toHaveAttribute("href", "http://erp.localhost:8088/#crm-quotes");
    expect(router.state.location.pathname).toBe("/dashboard/queue");
    expect(center).toBeInTheDocument();
    await waitFor(() => {
      expect(requests).toContain("/api/v1/notifications/erp:90/read");
    });
    fireEvent.click(item);
    expect(item).toHaveAttribute("aria-expanded", "false");
    server.events.removeAllListeners();
  });

  it("«Отметить все прочитанными» сбрасывает счётчик и подсветку", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const center = await openBell(/^Центр уведомлений, 3 новых/);

    fireEvent.click(within(center).getByRole("button", { name: "Отметить все прочитанными" }));

    expect(await screen.findByRole("button", { name: "Центр уведомлений" })).toBeInTheDocument();
    await waitFor(() => {
      expect(within(center).queryByText(/Новое:/)).toBeNull();
    });
    expect(
      within(center).getByRole("button", { name: "Отметить все прочитанными" }),
    ).toBeDisabled();
  });

  it("нет уведомлений — пустое состояние словами", async () => {
    signInAs("engineer@demo.example");
    renderApp("/dashboard/queue");
    const center = await openBell();

    expect(within(center).getByText("Новых уведомлений нет")).toBeInTheDocument();
    expect(
      within(center).getByText(/Решения, сообщения клиентов и системные события/),
    ).toBeInTheDocument();
  });

  it("ERP не отвечает: окно показывает плашку, а не пустоту", async () => {
    server.use(
      http.get("*/notifications", () =>
        HttpResponse.json({
          items: [],
          next_cursor: null,
          unread_count: 0,
          sources: { crm: "ok", erp: "unavailable" },
        }),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const center = await openBell();

    expect(await within(center).findByText("ERP не отвечает, данные неполные")).toBeInTheDocument();
  });

  it("сбой запроса: «Не удалось загрузить» и «Повторить»", async () => {
    server.use(
      http.get("*/notifications", () =>
        HttpResponse.json(
          { code: "INTERNAL_ERROR", message: "Ошибка сервера.", source: "bff" },
          { status: 500 },
        ),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const center = await openBell();

    expect(await within(center).findByText("Не удалось загрузить уведомления")).toBeInTheDocument();
    expect(within(center).getByRole("button", { name: "Повторить" })).toBeInTheDocument();
  });

  it("сегмент «Все» отображает полный список уведомлений прямо в шторке без деструктивного редиректа", async () => {
    signInAs("director@demo.example");
    const { router } = renderApp("/crm/leads");
    const center = await openBell();

    expect(within(center).queryByRole("link", { name: "Все уведомления" })).toBeNull();

    fireEvent.click(within(center).getByText("Все"));

    expect(router.state.location.pathname).toBe("/crm/leads");
    const list = await within(center).findByRole("list", { name: "Уведомления" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(7);
    expect(within(list).getByText(/КП-2026\/118 ждёт/)).toBeInTheDocument();
  });
});

describe("Боковое окно «Сегодня»", () => {
  it("лента событий компании: кто, что, модуль и время", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue?panel=open");

    const panel = await screen.findByRole("complementary", { name: "Боковое окно" });
    const feed = await within(panel).findByRole("list", { name: "События за сегодня" });
    expect(within(feed).getAllByRole("listitem")).toHaveLength(4);
    expect(within(feed).getByText("Демо Бухгалтерова (бухгалтер)")).toBeInTheDocument();
    expect(within(feed).getByText(/подтвердила оплату по ПР-2026-099/)).toBeInTheDocument();
  });

  it("административные события ERP — словами на языке сотрудника, не сырым глаголом (O-5)", async () => {
    const item = (id: string, code: string, text: string) => ({
      id,
      actor: { id: "", name: "Система", initials: "С" },
      text,
      code,
      module: "erp",
      at: new Date().toISOString(),
    });
    server.use(
      http.get("*/activity/today", () =>
        HttpResponse.json({
          items: [
            item("erp:1", "admin.lookup.deleted", "Deleted row text from BFF"),
            item("erp:2", "admin.email_template.created", "Created text from BFF"),
          ],
          sources: { crm: "ok", erp: "ok" },
        }),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue?panel=open");

    const panel = await screen.findByRole("complementary");
    const feed = await within(panel).findByRole("list", { name: "События за сегодня" });
    expect(await within(feed).findByText("Строка справочника удалена")).toBeInTheDocument();
    expect(within(feed).getByText("Шаблон письма добавлен")).toBeInTheDocument();
    expect(within(feed).queryByText(/BFF/)).not.toBeInTheDocument();
  });

  it("ERP не отвечает: лента пуста, но плашка объясняет почему", async () => {
    server.use(
      http.get("*/activity/today", () =>
        HttpResponse.json({ items: [], sources: { crm: "ok", erp: "unavailable" } }),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue?panel=open");

    const panel = await screen.findByRole("complementary", { name: "Боковое окно" });
    expect(await within(panel).findByText("ERP не отвечает, данные неполные")).toBeInTheDocument();
    expect(within(panel).getByText("Событий за день пока нет")).toBeInTheDocument();
  });
});
