import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { resetFeedMocks } from "../../../mocks/feedHandlers";
import { endSession } from "../../../mocks/mockSession";
import { resetTicketsMock } from "../../../mocks/ticketsStore";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
  resetFeedMocks();
  resetTicketsMock();
});
afterEach(() => {
  cleanup();
  endSession();
});

async function openState(email: string, path = "/admin") {
  signInAs(email);
  renderApp(path);
  return screen.findByRole("heading", { level: 1, name: "Состояние" });
}

const attention = () => screen.findByRole("region", { name: /^Требует внимания · \d+$/ });

describe("Настройки · «Состояние» (ЕВ-2а, доска 37)", () => {
  it("администратор: первый экран модуля — «Требует внимания», «Службы», «Готовность»; в меню «Состояние» первым", async () => {
    await openState("admin@demo.example");
    expect(await attention()).toBeVisible();
    expect(await screen.findByRole("region", { name: "Службы" })).toBeVisible();
    expect(await screen.findByRole("region", { name: /^Готовность · \d+ из \d+$/ })).toBeVisible();
    const menu = screen.getByRole("navigation", { name: "Разделы модуля" });
    // НАСТ-1: «Состояние», затем пять групп со всеми страницами сразу
    expect(within(menu).getAllByRole("link")[0]).toHaveTextContent("Состояние");
    expect(
      within(menu)
        .getAllByRole("group")
        .map((group) => group.querySelector("p")?.textContent),
    ).toEqual(["Люди и доступ", "Компания", "Правила работы", "Каналы и подключения", "Журнал"]);
  });

  it("внешняя проверка доступности — «не подключена», а не выдуманное «работает»", async () => {
    await openState("admin@demo.example");
    const services = await screen.findByRole("region", { name: "Службы" });
    const row = within(services).getByText("Внешняя проверка доступности").closest("li");
    expect(row).toHaveTextContent("не подключена");
    expect(row).toHaveTextContent("сообщение владельцу при сбое не придёт");
  });

  it("строка «Требует внимания» — из факта: полномочие подписи истекает → строка; нет такого полномочия → строки нет", async () => {
    await openState("admin@demo.example");
    const list = within(await attention());
    await waitFor(() => {
      expect(list.getByText(/Полномочие подписи истекает через \d+ дн\./)).toBeVisible();
    });
    const row = list.getByText(/Полномочие подписи истекает/).closest("li") as HTMLElement;
    expect(row).toHaveTextContent("после срока документы некому подписать");
    expect(row).not.toHaveTextContent("исправляет");
    expect(within(row).getByRole("link", { name: "Открыть «Права подписи»" })).toHaveAttribute(
      "href",
      "/admin/signing",
    );
    cleanup();

    server.use(
      http.get("*/eds/signing/authorities", () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    await openState("admin@demo.example");
    await attention();
    await waitFor(() => {
      expect(screen.queryByText(/Полномочие подписи истекает/)).toBeNull();
    });
  });

  it("курс не обновлялся → строка ведёт в «Налоги и валюты»; курс есть → строки нет", async () => {
    server.use(
      http.get("*/admin/company/fx-rate", ({ request }) =>
        HttpResponse.json({
          currency: new URL(request.url).searchParams.get("currency") ?? "USD",
          currencies: [],
          current: null,
          max_age_days: 3,
          journal: [],
          journal_available: false,
        }),
      ),
    );
    await openState("admin@demo.example");
    const list = within(await attention());
    const row = (await list.findByText(/Курс USD не обновлялся 3 дн\./)).closest(
      "li",
    ) as HTMLElement;
    expect(row).not.toHaveTextContent("исправляет");
    expect(within(row).getByRole("link", { name: "Открыть «Налоги и валюты»" })).toHaveAttribute(
      "href",
      "/admin/taxes",
    );
  });

  it("готовность не исчезает: шаги, бланк и адрес поддержки; «работает» — только где проверка службы подтверждает", async () => {
    await openState("admin@demo.example");
    const ready = await screen.findByRole("region", { name: /^Готовность · \d+ из \d+$/ });
    const items = await within(ready).findAllByRole("listitem");
    expect(items.length).toBeGreaterThan(5);
    const text = items.map((li) => li.textContent);
    expect(text.some((t) => /Бланк компании/.test(t))).toBe(true);
    expect(text.some((t) => /Адрес поддержки/.test(t))).toBe(true);
    // строки без проверки службы (администратор, компания) остаются «заполнено», а не «работает»
    const admin = items.find((li) => /Администратор/.test(li.textContent));
    expect(admin).toHaveTextContent("заполнено");
    expect(admin).not.toHaveTextContent("работает");
  });

  it("директор читает состояние: сбои и службы есть; шагов первого запуска и пункта «Каналы и подключения» нет, бланк и адрес поддержки — есть", async () => {
    await openState("director@demo.example");
    expect(await attention()).toBeVisible();
    const ready = await screen.findByRole("region", { name: /^Готовность · \d+ из \d+$/ });
    expect(within(ready).queryByRole("link", { name: "Продолжить настройку" })).toBeNull();
    expect(within(ready).queryByText("Администратор")).toBeNull();
    expect(await within(ready).findByText("Бланк компании")).toBeVisible();
    const menu = screen.getByRole("navigation", { name: "Разделы модуля" });
    expect(within(menu).queryByRole("group", { name: "Каналы и подключения" })).toBeNull();
    expect(within(menu).getByRole("group", { name: "Компания" })).toBeVisible();
  });

  it("строка сбоя службы: у директора нет кнопки на закрытую страницу «Telegram», у администратора есть; заголовок без названия поставщика", async () => {
    const broken = {
      checked_at: "2026-11-23T10:00:00Z",
      cards: [],
      attention: [
        {
          id: "bot:down",
          card: "telegram",
          severity: "fail",
          kind: "service",
          subject: "Ключ OpenAI отклонён",
          detail: null,
          technical: null,
          group: {
            key: "openai",
            headline: "Ключ OpenAI отклонён",
            detail: "Ключ не принят",
            owner: "admin",
            affected: [],
            count: 1,
          },
        },
      ],
    };
    server.use(http.get("*/admin/integrations", () => HttpResponse.json(broken)));
    await openState("director@demo.example");
    const list = within(await attention());
    const row = (await list.findByText("Telegram")).closest("li") as HTMLElement;
    // страница закрыта зрителю: должности не называем, говорим, что делать
    expect(row).toHaveTextContent("передайте тому, кто ведёт настройки");
    expect(row).not.toHaveTextContent("исправляет");
    expect(row).not.toHaveTextContent("OpenAI");
    expect(within(row).queryByRole("link")).toBeNull();
    cleanup();

    server.use(http.get("*/admin/integrations", () => HttpResponse.json(broken)));
    await openState("admin@demo.example");
    const adminRow = (await within(await attention()).findByText("Telegram")).closest(
      "li",
    ) as HTMLElement;
    expect(within(adminRow).getByRole("link", { name: "Открыть «Telegram»" })).toHaveAttribute(
      "href",
      "/admin/telegram",
    );
  });

  it("зоны без ответственного (ЕВ-З): N > 0 → строка с кнопкой «Зоны ответственности»; N = 0 → строки нет", async () => {
    const summary = (without: number) =>
      http.get("*/admin/responsibility-zones/summary", () =>
        HttpResponse.json({ zones_total: 5, without_responsible: without, with_problems: 0 }),
      );
    server.use(summary(2));
    await openState("admin@demo.example");
    const row = (await within(await attention()).findByText("Зон без ответственного: 2")).closest(
      "li",
    ) as HTMLElement;
    expect(
      within(row).getByRole("link", { name: "Открыть «Зоны ответственности»" }),
    ).toHaveAttribute("href", "/admin/zones");
    cleanup();

    server.use(summary(0));
    await openState("admin@demo.example");
    await attention();
    await screen.findByRole("region", { name: "Службы" });
    expect(screen.queryByText(/Зон без ответственного/)).toBeNull();
  });

  it("⚙ из других модулей (`?group=`) ведёт на первую страницу группы, а не на «Состояние»", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin?group=channels");
    expect(await screen.findByRole("heading", { level: 1, name: "Telegram" })).toBeVisible();
  });

  it("сотрудник с одним `company.settings` без `admin` уходит на свою первую страницу", async () => {
    signInAs("accountant@demo.example");
    renderApp("/admin");
    await waitFor(() => {
      expect(screen.queryByRole("heading", { level: 1, name: "Состояние" })).toBeNull();
    });
  });
});
