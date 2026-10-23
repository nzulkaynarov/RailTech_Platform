import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { endSession } from "../../mocks/mockSession";
import { usePanelsStore } from "../../app/shell/panelsStore";
import i18n from "../../shared/i18n";
import { POLL_INTERVAL_MS, STREAM_POLL_INTERVAL_MS } from "../../shared/api/polling";
import { FakeEventSource } from "../../test/fakeEventSource";
import { renderApp, signInAs } from "../../test/renderApp";
import { server } from "../../test/server";
import { setViewportWidth } from "../../test/viewport";
import { ROLE_ID } from "../../test/roles";

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

async function main() {
  await screen.findByRole("heading", { level: 1, name: "Моя очередь" });
  return screen.getByRole("main");
}

describe("Dashboard · Моя очередь", () => {
  it("директор: подзаголовок с числом решений, четыре счётчика и три строки очереди", async () => {
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText(/Директор · .* · 3 решения/)).toBeVisible();
    const cards = within(page).getByRole("region", { name: "Счётчики очереди" });
    expect(within(cards).getAllByRole("link")).toHaveLength(4);
    expect(within(cards).getByRole("link", { name: /Входящие без резолюции/ })).toHaveAttribute(
      "href",
      "/eds/inbox",
    );

    const queue = await within(page).findByRole("region", { name: "Что сделать сейчас" });
    const rows = within(queue).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0] as HTMLElement).getByText("срок сегодня")).toBeVisible();
    expect(within(rows[1] as HTMLElement).getByText("завтра")).toBeVisible();
    expect(within(rows[2] as HTMLElement).getByText("служебка")).toBeVisible();
    const open = within(rows[0] as HTMLElement).getByRole("link", { name: /Открыть/ });
    expect(open).toHaveAttribute(
      "href",
      "/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution",
    );
  });

  it("менеджер видит свои строки из CRM; плашки источников нет", async () => {
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Взять в работу лида L-2041")).toBeVisible();
    expect(within(page).getByText("Ответить лиду L-2050")).toBeVisible();
    expect(within(page).getByText(/Менеджер · .* · 2 решения/)).toBeVisible();
    expect(within(page).queryByRole("status")).toBeNull();
  });

  it("пустая очередь: слова SPEC-v3 §7.1 и действие", async () => {
    signInAs("supply@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Решений от вас пока не требуется")).toBeVisible();
    expect(
      within(page).getByText(
        "Новые письма приходят из CRM, черновики КП — из ERP, служебки — от сотрудников.",
      ),
    ).toBeVisible();
    expect(within(page).getByRole("link", { name: "Все проекты" })).toBeVisible();
    expect(within(page).getByText(/0 решений/)).toBeVisible();
  });

  it("ERP не отвечает: данные CRM остаются, сверху плашка «ERP не отвечает»", async () => {
    server.use(
      http.get("*/queue", () =>
        HttpResponse.json({
          items: [
            {
              id: "lead:1",
              role: "MANAGER",
              kind: "take_lead",
              title: "Взять в работу лида L-0001",
              subtitle: "Демо Клиентов",
              due_label: "today",
              object: {
                kind: "lead",
                number: "L-0001",
                path: "/crm/leads?lead=L-0001&panel=open&tab=card",
              },
            },
          ],
          sources: { crm: "ok", erp: "unavailable" },
        }),
      ),
    );
    signInAs("manager@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Взять в работу лида L-0001")).toBeVisible();
    expect(within(page).getByRole("status")).toHaveTextContent("ERP не отвечает, данные неполные");
  });

  it("сбой запроса: экран с причиной и «Повторить», после повтора данные появляются", async () => {
    let calls = 0;
    server.use(
      http.get("*/queue", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json(
              { code: "INTERNAL_ERROR", message: "Ошибка сервера.", source: "bff" },
              { status: 500 },
            )
          : HttpResponse.json({ items: [], sources: { crm: "ok", erp: "ok" } });
      }),
    );
    signInAs("director@demo.example");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Не удалось загрузить очередь")).toBeVisible();
    fireEvent.click(within(page).getByRole("button", { name: "Повторить" }));
    expect(await within(page).findByText("Решений от вас пока не требуется")).toBeVisible();
  });

  it("смена активной роли: запрос уходит с role, очередь пересчитывается", async () => {
    const seen: (string | null)[] = [];
    server.events.on("request:start", ({ request }) => {
      const url = new URL(request.url);
      if (url.pathname.endsWith("/queue")) seen.push(url.searchParams.get("role"));
    });
    signInAs("all@demo.example", "MANAGER");
    renderApp("/dashboard/queue");
    const page = await main();

    expect(await within(page).findByText("Взять в работу лида L-2041")).toBeVisible();
    expect(within(page).queryByText(/Наложить резолюцию/)).toBeNull();
    expect(seen).toContain(ROLE_ID.MANAGER);
    server.events.removeAllListeners();
  });

  it("опрос: очередь и счётчики запрашиваются каждые 30 с и при возврате на вкладку", async () => {
    signInAs("director@demo.example");
    const { queryClient } = renderApp("/dashboard/queue");
    await main();

    await waitFor(() => {
      const queries = queryClient.getQueryCache().findAll({ queryKey: ["/api/v1/queue"] });
      expect(queries.length).toBeGreaterThan(0);
    });
    const watched = queryClient
      .getQueryCache()
      .getAll()
      .filter((q) => /\/api\/v1\/(queue|notifications|menu-counters)/.test(String(q.queryKey[0])));
    expect(watched.length).toBeGreaterThanOrEqual(4);
    for (const query of watched) {
      const options = query.observers[0]?.options;
      expect(options?.refetchInterval, String(query.queryKey[0])).toBe(POLL_INTERVAL_MS);
      expect(options?.refetchOnWindowFocus).toBe(true);
    }
    expect(POLL_INTERVAL_MS).toBe(30_000);
  });

  describe("поток подсказок BFF (SSE)", () => {
    beforeEach(() => {
      FakeEventSource.reset();
      vi.stubGlobal("EventSource", FakeEventSource);
    });
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    function countRequests() {
      const hits = { queue: 0, cards: 0, counters: 0, notifications: 0 };
      server.events.on("request:start", ({ request }) => {
        const path = new URL(request.url).pathname;
        if (path === "/api/v1/queue") hits.queue += 1;
        if (path === "/api/v1/queue/cards") hits.cards += 1;
        if (path === "/api/v1/menu-counters") hits.counters += 1;
        if (path === "/api/v1/notifications") hits.notifications += 1;
      });
      return hits;
    }

    it("подсказка обновляет очередь, карточки, счётчики и колокольчик без опроса; опрос при живом потоке редкий", async () => {
      signInAs("director@demo.example");
      const hits = countRequests();
      const { queryClient } = renderApp("/dashboard/queue");
      await main();
      await waitFor(() => {
        expect(FakeEventSource.instances).toHaveLength(1);
        expect(hits.queue + hits.cards + hits.counters + hits.notifications).toBeGreaterThanOrEqual(
          4,
        );
      });
      act(() => {
        FakeEventSource.last.open();
      });
      const before = { ...hits };

      for (const query of queryClient.getQueryCache().getAll()) {
        if (/\/api\/v1\/(queue|notifications|menu-counters)/.test(String(query.queryKey[0]))) {
          expect(query.observers[0]?.options.refetchInterval).toBe(STREAM_POLL_INTERVAL_MS);
        }
      }

      act(() => {
        FakeEventSource.last.emit("invalidate", {
          topics: ["queue", "counters", "notifications"],
          reason: "uz.railtech.erp.quote.sent.v1",
        });
      });
      await waitFor(() => {
        expect(hits.queue).toBe(before.queue + 1);
        expect(hits.cards).toBe(before.cards + 1);
        expect(hits.counters).toBe(before.counters + 1);
        expect(hits.notifications).toBe(before.notifications + 1);
      });
    });

    it("поток оборвался — опрос возвращается к 30 с", async () => {
      signInAs("director@demo.example");
      const { queryClient } = renderApp("/dashboard/queue");
      await main();
      await waitFor(() => {
        expect(FakeEventSource.instances).toHaveLength(1);
      });
      act(() => {
        FakeEventSource.last.open();
      });
      act(() => {
        FakeEventSource.last.fail();
      });
      await waitFor(() => {
        const watched = queryClient
          .getQueryCache()
          .getAll()
          .filter((q) =>
            /\/api\/v1\/(queue|notifications|menu-counters)/.test(String(q.queryKey[0])),
          );
        expect(watched.length).toBeGreaterThanOrEqual(4);
        for (const query of watched) {
          expect(query.observers[0]?.options.refetchInterval).toBe(POLL_INTERVAL_MS);
        }
      });
    });
  });
});
