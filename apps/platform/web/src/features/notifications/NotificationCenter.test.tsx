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
  return screen.findByRole("region", { name: "Центр уведомлений" });
}

describe("Центр уведомлений", () => {
  it("колокольчик показывает число непрочитанных, окно — вкладки с числами и список", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");

    expect(
      await screen.findByRole("button", { name: "Центр уведомлений, 3 новых" }),
    ).toBeInTheDocument();
    const center = await openBell(/^Центр уведомлений, 3 новых/);

    const tabs = within(center).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Все 3", "Решения 2", "Клиенты 1", "Система"]);
    const list = await within(center).findByRole("list", { name: "Уведомления" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(5);
    // непрочитанное помечено словом, не только цветом
    const first = within(list).getAllByRole("link")[0] as HTMLElement;
    expect(first).toHaveTextContent("Новое: КП-2026/118 ждёт вашего согласования");
    expect(first).toHaveAttribute(
      "href",
      "/eds/drafts/%D0%9A%D0%9F-2026%2F118?panel=open&tab=approve",
    );
  });

  it("вкладка «Клиенты» оставляет только свои уведомления", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const center = await openBell();

    fireEvent.click(within(center).getByRole("tab", { name: /^Клиенты/ }));

    const list = await within(center).findByRole("list", { name: "Уведомления" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).queryByText(/КП-2026\/118 ждёт/)).toBeNull();
  });

  it("клик по уведомлению отмечает его прочитанным, открывает объект и нужную вкладку бокового окна", async () => {
    signInAs("director@demo.example");
    const { router } = renderApp("/dashboard/queue");
    const center = await openBell();
    const requests: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.method === "POST") requests.push(new URL(request.url).pathname);
    });

    fireEvent.click(await within(center).findByRole("link", { name: /КП-2026\/118 ждёт/ }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/eds/drafts/%D0%9A%D0%9F-2026%2F118");
    });
    expect(router.state.location.search).toBe("?panel=open&tab=approve");
    expect(
      await screen.findByRole("tab", { name: "Одобрение", selected: true }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Центр уведомлений, 2 новых" }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(requests).toContain("/api/v1/notifications/erp:1/read");
    });
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

  it("«Все уведомления» открывает вкладку «Уведомления» бокового окна «Моей очереди»", async () => {
    signInAs("director@demo.example");
    const { router } = renderApp("/crm/leads");
    const center = await openBell();

    fireEvent.click(within(center).getByRole("link", { name: "Все уведомления" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/dashboard/queue");
    });
    expect(router.state.location.search).toBe("?panel=open&tab=notifications");
    expect(
      await screen.findByRole("tab", { name: "Уведомления", selected: true }),
    ).toBeInTheDocument();
    const panel = screen.getByRole("complementary", { name: "Боковое окно" });
    expect(await within(panel).findByText(/КП-2026\/118 ждёт/)).toBeInTheDocument();
  });
});

describe("Боковое окно «Сегодня»", () => {
  it("лента событий компании: кто, что, модуль и время", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");

    const panel = await screen.findByRole("complementary", { name: "Боковое окно" });
    const feed = await within(panel).findByRole("list", { name: "События за сегодня" });
    expect(within(feed).getAllByRole("listitem")).toHaveLength(4);
    expect(within(feed).getByText("Демо Бухгалтерова (бухгалтер)")).toBeInTheDocument();
    expect(within(feed).getByText(/подтвердила оплату по ПР-2026-099/)).toBeInTheDocument();
  });

  it("ERP не отвечает: лента пуста, но плашка объясняет почему", async () => {
    server.use(
      http.get("*/activity/today", () =>
        HttpResponse.json({ items: [], sources: { crm: "ok", erp: "unavailable" } }),
      ),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");

    const panel = await screen.findByRole("complementary", { name: "Боковое окно" });
    expect(await within(panel).findByText("ERP не отвечает, данные неполные")).toBeInTheDocument();
    expect(within(panel).getByText("Событий за день пока нет")).toBeInTheDocument();
  });
});
