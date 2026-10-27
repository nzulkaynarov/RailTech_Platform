import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../test/server";
import { panelEl, renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";

setupLetterTests();

async function openInbox(email: string, path = "/eds/inbox") {
  signIn(email);
  const view = renderAt(path);
  // список — заголовок раздела из `modules`; карточка — «Письмо ВХ-…», его проверяет сам тест
  if (path === "/eds/inbox") {
    expect(await screen.findByRole("heading", { level: 1, name: "Входящие письма" })).toBeVisible();
  }
  return view;
}

function row(number: string): HTMLElement {
  const link = screen.getByRole("link", { name: `Показать письмо ${number} в боковом окне` });
  const tr = link.closest("tr");
  if (!tr) throw new Error(`нет строки ${number}`);
  return tr;
}

describe("EDS · Входящие письма: список", () => {
  it("по умолчанию — «Ждёт резолюции»: номер, тема, клиент, заявка, получено, статус словом, «Открыть»", async () => {
    await openInbox("director@demo.example");

    expect(await screen.findByRole("table")).toBeVisible();
    const first = row("ВХ-104/26");
    expect(
      within(first).getByText("Запрос коммерческого предложения на стрелочные приводы"),
    ).toBeVisible();
    expect(within(first).getByText("ООО «Демо-Рейл»")).toBeVisible();
    expect(within(first).getByText("ЗВ-2026-104")).toBeVisible();
    expect(within(first).getByText("24.10.2026")).toBeVisible();
    expect(within(first).getByText("Ждёт резолюции")).toBeVisible();
    expect(within(first).getByText("Срочно")).toBeVisible();
    expect(
      within(first).getByRole("link", { name: "Открыть карточку письма ВХ-104/26" }),
    ).toHaveAttribute("href", "/eds/inbox/%D0%92%D0%A5-104%2F26");
    // решённые письма в этот фильтр не попадают
    expect(
      screen.queryByRole("link", { name: "Показать письмо ВХ-101/26 в боковом окне" }),
    ).toBeNull();
    expect(screen.getAllByRole("row")).toHaveLength(1 + 4);
  });

  it("фильтр по статусу: «Резолюция наложена», «Возвращено», «Отклонено» и «Все»", async () => {
    await openInbox("director@demo.example");
    await screen.findByRole("table");
    const filter = screen.getByRole("radiogroup", { name: "Статус письма" });

    fireEvent.click(within(filter).getByText("Резолюция наложена"));
    expect(
      await screen.findByRole("link", { name: "Показать письмо ВХ-101/26 в боковом окне" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("link", { name: "Показать письмо ВХ-104/26 в боковом окне" }),
    ).toBeNull();

    fireEvent.click(within(filter).getByText("Отклонено"));
    expect(
      await screen.findByRole("link", { name: "Показать письмо ВХ-103/26 в боковом окне" }),
    ).toBeVisible();

    fireEvent.click(within(filter).getByText("Все"));
    await waitFor(() => {
      expect(screen.getAllByRole("row")).toHaveLength(1 + 7);
    });
  });

  it("пустое состояние словами и с действием: нет писем, ждущих резолюции", async () => {
    server.use(
      http.get("*/eds/letters", ({ request }) =>
        new URL(request.url).searchParams.has("status")
          ? HttpResponse.json({ items: [], next_cursor: null })
          : HttpResponse.json({
              items: [
                {
                  id: "20000000-0000-4000-8000-000000000101",
                  number: "ВХ-101/26",
                  subject: "Решённое письмо",
                  client_name: "ООО «Демо»",
                  request_number: null,
                  received_at: "2026-10-24",
                  status: "resolved",
                  urgent: false,
                  due: null,
                },
              ],
              next_cursor: null,
            }),
      ),
    );
    await openInbox("director@demo.example");

    expect(
      await screen.findByRole("heading", { name: "Решений от вас пока не требуется" }),
    ).toBeVisible();
    expect(screen.getByText(/Новые письма приходят из CRM после создания заявки/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Показать все письма" }));
    expect(await screen.findByRole("table")).toBeVisible();
  });

  it("«Показать ещё» подгружает следующую страницу по курсору", async () => {
    const item = (n: number) => ({
      id: `20000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
      number: `ВХ-${String(n)}/26`,
      subject: `Письмо ${String(n)}`,
      client_name: "ООО «Демо»",
      request_number: null,
      received_at: "2026-10-24",
      status: "awaiting_resolution",
      urgent: false,
      due: null,
    });
    server.use(
      http.get("*/eds/letters", ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        return HttpResponse.json(
          cursor
            ? { items: [item(202)], next_cursor: null }
            : { items: [item(201)], next_cursor: "p2" },
        );
      }),
    );
    await openInbox("director@demo.example");

    expect(await screen.findByText("Письмо 201")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Показать ещё" }));
    expect(await screen.findByText("Письмо 202")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();
  });

  it("EDS не отвечает — слова и «Повторить», а не пустой экран", async () => {
    server.use(
      http.get("*/eds/letters", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "Сервис временно недоступен.", source: "eds" },
          { status: 503 },
        ),
      ),
    );
    await openInbox("director@demo.example");

    expect(
      await screen.findByRole("heading", { name: "Документооборот не отвечает" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });

  it("нет доступа к EDS (`eds_not_granted`) — отдельное объяснение", async () => {
    server.use(
      http.get("*/eds/letters", () =>
        HttpResponse.json(
          {
            code: "FORBIDDEN",
            message: "Нет доступа к EDS.",
            source: "eds",
            details: { reason: "eds_not_granted" },
          },
          { status: 403 },
        ),
      ),
    );
    await openInbox("director@demo.example");

    expect(
      await screen.findByRole("heading", { name: "Нет доступа к документообороту" }),
    ).toBeVisible();
  });
});

describe("EDS · Входящие письма: боковое окно из списка", () => {
  it("клик по строке открывает письмо и форму «Резолюция» в боковом окне без перехода", async () => {
    const { router } = await openInbox("director@demo.example");
    await screen.findByRole("table");

    fireEvent.click(within(row("ВХ-105/26")).getByText("Цены на рельсовые скрепления"));

    const panel = await panelEl();
    expect(
      await within(panel).findByRole("heading", { level: 3, name: "ВХ-105/26" }),
    ).toBeVisible();
    expect(
      within(panel).getByText("Нужен расчёт на 4 000 комплектов скреплений для участка пути."),
    ).toBeVisible();
    expect(await within(panel).findByRole("form", { name: "Резолюция директора" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/eds/inbox");
    expect(router.state.location.search).toContain("letter=");
    expect(within(panel).getByRole("link", { name: "Открыть карточку письма" })).toHaveAttribute(
      "href",
      "/eds/inbox/%D0%92%D0%A5-105%2F26",
    );
  });

  it("менеджер видит письмо в окне только для чтения: без формы и кнопок решения", async () => {
    await openInbox("manager@demo.example");
    await screen.findByRole("table");

    fireEvent.click(within(row("ВХ-104/26")).getByText("ООО «Демо-Рейл»"));

    const panel = await panelEl();
    expect(
      await within(panel).findByRole("heading", { name: "Письмо ждёт резолюции директора" }),
    ).toBeVisible();
    expect(within(panel).queryByRole("form")).toBeNull();
    expect(within(panel).queryByRole("button", { name: /Утвердить резолюцию/ })).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Отклонить" })).toBeNull();
  });
});

describe("EDS · Входящие письма: карточка", () => {
  it("шкала 7 шагов (текущий — Резолюция), реквизиты, суть, вложения, связи", async () => {
    await openInbox("director@demo.example", "/eds/inbox/%D0%92%D0%A5-104%2F26");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Письмо ВХ-104/26" }),
    ).toBeVisible();
    const steps = screen.getByRole("list", { name: "Путь заявки ЗВ-2026-104" });
    const current = within(steps).getByText("Резолюция").closest("li");
    expect(current).toHaveAttribute("aria-current", "step");
    expect(within(steps).getAllByRole("listitem")).toHaveLength(7);

    expect(screen.getByText("ООО «Демо-Рейл»", { selector: "dd" })).toBeVisible();
    expect(screen.getByText("300123456", { selector: "dd" })).toBeVisible();
    expect(screen.getByText("исх-24 · 22.10.2026")).toBeVisible();
    expect(screen.getByText(/Просим рассмотреть поставку 12 стрелочных приводов/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Скачать файл запрос-на-кп.pdf" })).toHaveAttribute(
      "href",
      "/api/v1/eds/letter-files/30000000-0000-4000-8000-000000000001",
    );
    expect(screen.getByRole("link", { name: "ЗВ-2026-104" })).toBeVisible();
    expect(screen.getByRole("link", { name: "ООО «Демо-Рейл»" })).toHaveAttribute(
      "href",
      "/crm/clients/42",
    );
    expect(screen.getByText("Ждёт резолюции")).toBeVisible();
  });

  it("номер со «/» без кодирования (`/eds/inbox/ВХ-104/26`) тоже открывает письмо", async () => {
    await openInbox("director@demo.example", "/eds/inbox/ВХ-104/26");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Письмо ВХ-104/26" }),
    ).toBeVisible();
  });

  it("письмо по id открывается так же, как по номеру", async () => {
    await openInbox("director@demo.example", "/eds/inbox/20000000-0000-4000-8000-000000000105");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Письмо ВХ-105/26" }),
    ).toBeVisible();
  });

  it("ERP не ответил — частичная карточка с плашкой, а не пустой экран", async () => {
    await openInbox("director@demo.example", "/eds/inbox/%D0%92%D0%A5-107%2F26");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Письмо ВХ-107/26" }),
    ).toBeVisible();
    expect(screen.getByText("ERP не отвечает, данные неполные")).toBeVisible();
    expect(screen.getByText("Поставка кабельной продукции")).toBeVisible();
    expect(screen.getByRole("list", { name: /Путь заявки/ })).toBeVisible();
  });

  it("решённое письмо: «Решение директора» и история; отклонённое — шаг «Отказ» и причина", async () => {
    await openInbox("director@demo.example", "/eds/inbox/%D0%92%D0%A5-101%2F26");
    expect(await screen.findByRole("heading", { name: "Решение директора" })).toBeVisible();
    expect(
      screen.getByText("Посчитать с запасом по складу, срок поставки — до конца ноября.", {
        selector: "dd",
      }),
    ).toBeVisible();
    expect(screen.getByText("15 %")).toBeVisible();
    expect(screen.getByText("30.10.2026")).toBeVisible();
    expect(screen.getByText("Резолюция наложена", { selector: "strong" })).toBeVisible();
  });

  it("отклонённое письмо: причина и тег «Отказ» на шкале", async () => {
    await openInbox("director@demo.example", "/eds/inbox/%D0%92%D0%A5-103%2F26");

    expect(await screen.findByText("Не наш профиль.")).toBeVisible();
    expect(screen.getAllByText("Отказ").length).toBeGreaterThan(0);
  });

  it("менеджер читает карточку без кнопок решения, с пометкой «Только просмотр»", async () => {
    await openInbox("manager@demo.example", "/eds/inbox/%D0%92%D0%A5-104%2F26");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Письмо ВХ-104/26" }),
    ).toBeVisible();
    expect(screen.getByText("Только просмотр")).toBeVisible();
    expect(screen.queryByRole("button", { name: /резолюц/i })).toBeNull();
    const panel = await panelEl();
    expect(await within(panel).findByText("Письмо ждёт резолюции директора")).toBeVisible();
  });

  it("неизвестное письмо — «Письмо не найдено» со ссылкой на список", async () => {
    await openInbox("director@demo.example", "/eds/inbox/%D0%92%D0%A5-999%2F26");

    expect(await screen.findByRole("heading", { name: "Письмо не найдено" })).toBeVisible();
    expect(screen.getByRole("link", { name: "К списку писем" })).toHaveAttribute(
      "href",
      "/eds/inbox",
    );
  });

  it("роль без раздела «Входящие» получает экран «Нет доступа»", async () => {
    signIn("supply@demo.example");
    renderAt("/eds/inbox");

    expect(await screen.findByText(/нет доступа|не положен/i)).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
