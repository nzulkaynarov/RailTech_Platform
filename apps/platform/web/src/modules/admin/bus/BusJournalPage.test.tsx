import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { readBus, resetBus } from "../../../mocks/fixtures/bus";
import { server } from "../../../test/server";
import { panelEl, renderAt, setupIntegrationsTests, signIn } from "../integrations/testkit";

setupIntegrationsTests();
beforeEach(() => {
  resetBus();
});

function card(domain: "CRM" | "ERP" | "EDS"): HTMLElement {
  const heading = screen.getByRole("heading", { level: 3, name: `${domain} отправляет` });
  const element = heading.closest<HTMLElement>(".ant-card");
  if (!element) throw new Error(`нет карточки ${domain}`);
  return element;
}

function row(container: HTMLElement, text: string): HTMLElement {
  const cell = within(container).getByText(text, { exact: true });
  const element = cell.closest<HTMLElement>("tr");
  if (!element) throw new Error(`нет строки ${text}`);
  return element;
}

describe("Admin · Журнал интеграций: подписчики", () => {
  it("администратор видит подписчиков трёх доменов с состоянием словом и счётчики сверху", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/bus");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Обмен между системами" }),
    ).toBeVisible();
    await screen.findByRole("heading", { level: 3, name: "CRM отправляет" });

    const crm = card("CRM");
    expect(within(row(crm, "ERP")).getByText("Есть недоставленные")).toBeVisible();
    expect(within(row(crm, "Платформа")).getByText("Ошибки подряд")).toBeVisible();
    expect(within(row(crm, "EDS")).getByText("Работает")).toBeVisible();
    const erp = card("ERP");
    const paused = row(erp, "CRM");
    expect(within(paused).getByText("Пауза")).toBeVisible();
    expect(within(paused).getByText(/^до \d{2}:\d{2}$/)).toBeVisible();
    expect(within(row(card("EDS"), "Платформа")).getByText("Выключен")).toBeVisible();

    // Счётчики: 4 в DLQ (3 у CRM → ERP, 1 у ERP → CRM), 1 подписчик на паузе
    const dlq = screen.getByRole("link", { name: /Недоставлено \(DLQ\)/ });
    expect(within(dlq).getByText("4")).toBeVisible();
    const pausedCounter = screen.getByRole("link", { name: /Подписчики на паузе/ });
    expect(within(pausedCounter).getByText("1")).toBeVisible();
  });

  it("«Повторить все dead» подписчика: «Что произойдёт», одна кнопка, итог и пересчёт сводки", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/bus");
    await screen.findByRole("heading", { level: 3, name: "CRM отправляет" });

    fireEvent.click(
      within(card("CRM")).getByRole("button", {
        name: "Повторить все dead: ERP (CRM)",
      }),
    );
    const panel = await panelEl();
    expect(
      await within(panel).findByRole("heading", { name: "Повторить все недоставленные · ERP" }),
    ).toBeVisible();
    const consequence = within(panel).getByRole("group", { name: "Что произойдёт" });
    expect(
      within(consequence).getByText(/Все доставки этого подписчика из DLQ \(3\)/),
    ).toBeVisible();
    expect(within(consequence).getByText(/Сначала исправьте причину/)).toBeVisible();

    fireEvent.click(within(panel).getByRole("button", { name: "Повторить 3" }));
    expect(await within(panel).findByText("Поставлены на повтор 3 доставки.")).toBeVisible();
    await waitFor(() => {
      expect(within(row(card("CRM"), "ERP")).getByText("Работает")).toBeVisible();
    });
    expect(readBus().deliveries.filter((d) => d.status === "dead")).toHaveLength(1);
  });
});

describe("Admin · Журнал интеграций: доставки, DLQ и входящие", () => {
  it("DLQ: недоставленные всех доменов; «Повторить доставку» в боковом окне", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/bus?view=dlq");

    const table = await screen.findByRole("table", { name: "Недоставленные события (DLQ)" });
    await waitFor(() => {
      expect(within(table).getAllByRole("row")).toHaveLength(5); // заголовок + 4
    });
    expect(within(table).getAllByText("Не доставлено")).toHaveLength(4);
    // Тела событий нет — только тип, объект, ответ
    expect(within(table).getAllByText("HTTP 404: Not Found")).toHaveLength(3);

    fireEvent.click(
      within(table).getByRole("button", { name: "Подробнее: erp.invoice.issued → CRM" }),
    );
    const panel = await panelEl();
    expect(await within(panel).findByText("uz.railtech.erp.invoice.issued.v1")).toBeVisible();
    expect(within(panel).getByText(/Тело события в журнал не выводится/)).toBeVisible();
    expect(within(panel).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: /Повторить доставку/ }));
    expect(await within(panel).findByText(/Поставлено на повтор/)).toBeVisible();
    await waitFor(() => {
      expect(within(table).getAllByText("Не доставлено")).toHaveLength(3);
    });
  });

  it("доставки: фильтры уходят в BFF, сброс фильтров возвращает всё", async () => {
    const seen: URL[] = [];
    server.events.on("request:start", ({ request }) => {
      const url = new URL(request.url);
      if (url.pathname.endsWith("/admin/bus/deliveries")) seen.push(url);
    });
    signIn("admin@demo.example");
    renderAt("/admin/bus?view=deliveries");
    const table = await screen.findByRole("table", { name: "Доставки событий подписчикам" });
    await waitFor(() => {
      expect(within(table).getAllByRole("row").length).toBeGreaterThan(10);
    });

    fireEvent.change(screen.getByLabelText("Тип события содержит"), {
      target: { value: "quote" },
    });
    await waitFor(() => {
      expect(seen.at(-1)?.searchParams.get("type")).toBe("quote");
    });
    await waitFor(() => {
      expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2);
    });
    expect(screen.getByText("Ждёт повтора")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Тип события содержит"), {
      target: { value: "nothing-like-this" },
    });
    expect(await screen.findByRole("heading", { name: "Доставок не найдено" })).toBeVisible();
    fireEvent.click(screen.getAllByRole("button", { name: "Сбросить фильтры" })[0] as HTMLElement);
    await waitFor(() => {
      expect(seen.at(-1)?.searchParams.get("type")).toBeNull();
    });
    server.events.removeAllListeners();
  });

  it("входящие с ошибками: «Повторить обработку» убирает запись из списка", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/bus?view=inbox");
    const table = await screen.findByRole("table", {
      name: "Принятые события, обработка которых упала",
    });
    await waitFor(() => {
      expect(within(table).getAllByRole("row")).toHaveLength(4);
    });
    expect(within(table).getByText("Ждёт повтора")).toBeVisible();
    expect(within(table).getAllByText("Ошибка обработки")).toHaveLength(2);

    fireEvent.click(within(table).getByRole("button", { name: "Подробнее: erp.deal.won в CRM" }));
    const panel = await panelEl();
    fireEvent.click(await within(panel).findByRole("button", { name: "Повторить обработку" }));
    expect(await within(panel).findByText(/Поставлено на повтор/)).toBeVisible();
    await waitFor(() => {
      expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(3);
    });
  });

  it("домен не ответил — плашка словами, остальные домены на месте", async () => {
    server.use(
      http.get("*/admin/bus", () =>
        HttpResponse.json({
          domains: [
            {
              domain: "crm",
              outbox_pending: 0,
              oldest_undelivered_age_seconds: null,
              dlq_size: 0,
              inbox_received: 0,
              inbox_retrying: 0,
              inbox_failed: 0,
              subscribers: [],
            },
          ],
          sources: { crm: "ok", erp: "unavailable", eds: "forbidden" },
        }),
      ),
    );
    signIn("admin@demo.example");
    renderAt("/admin/bus");
    const note = await screen.findByText(/ERP не отвечает — данные журнала неполные\./);
    expect(note).toHaveTextContent(/EDS не дал доступ к журналу/);
    expect(screen.getByText(/У CRM пока нет подписчиков/)).toBeVisible();
  });
});

describe("Admin · Журнал интеграций: права", () => {
  it.each(["director@demo.example", "manager@demo.example"])(
    "%s: пункта нет в подменю, прямой адрес — экран «Нет доступа»",
    async (email) => {
      signIn(email);
      renderAt("/admin/bus");
      expect(await screen.findByRole("heading", { level: 1 })).toBeVisible();
      expect(screen.queryByRole("link", { name: "Обмен между системами" })).toBeNull();
      expect(screen.queryByRole("heading", { level: 1, name: "Обмен между системами" })).toBeNull();
    },
  );

  it("администратор видит пункт «Журнал интеграций» в подменю Admin", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org");
    expect(await screen.findByRole("link", { name: "Обмен между системами" })).toBeVisible();
  });
});
