import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../test/server";
import { panelEl, renderAt, signIn, setupIntegrationsTests } from "./testkit";

setupIntegrationsTests();

const KEYS: Record<string, string> = {
  ERP: "erp",
  Telegram: "telegram",
  Почта: "mail",
  "Внешние сервисы": "services",
  "Модели ИИ": "models",
  Расходы: "spend",
  "Хранилище и бэкапы": "storage",
  "Состояние системы": "system",
};

/** Карточка экрана по названию; в боковом окне заголовок может совпадать, поэтому ищем по `data-card`. */
function tile(name: string): HTMLElement {
  const article = document.querySelector<HTMLElement>(`article[data-card="${KEYS[name] ?? name}"]`);
  if (!article) throw new Error(`нет карточки ${name}`);
  return article;
}

describe("Admin · Внешние интеграции: обзор", () => {
  it("администратор: «Требует внимания» вверху, восемь карточек, у каждой статус словом и последняя проверка", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/integrations");

    expect(await screen.findByRole("heading", { level: 1, name: "Подключения" })).toBeVisible();
    const attention = await screen.findByRole("heading", { level: 2, name: "Требует внимания" });
    // «Требует внимания» стоит раньше карточек
    const cards = screen.getByRole("heading", { level: 2, name: "Сервисы" });
    expect(
      attention.compareDocumentPosition(cards) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    const titles = screen
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent)
      .filter((text) =>
        [
          "ERP",
          "Telegram",
          "Почта",
          "Внешние сервисы",
          "Модели ИИ",
          "Расходы",
          "Хранилище и бэкапы",
          "Состояние системы",
        ].includes(text),
      );
    expect(titles).toEqual([
      "ERP",
      "Telegram",
      "Почта",
      "Внешние сервисы",
      "Модели ИИ",
      "Расходы",
      "Хранилище и бэкапы",
      "Состояние системы",
    ]);

    // Статус пятью уровнями — всегда словом.
    expect(within(tile("ERP")).getByText("Работает")).toBeVisible();
    expect(within(tile("Почта")).getByText("Внимание")).toBeVisible();
    expect(within(tile("Модели ИИ")).getByText("Сбой")).toBeVisible();
    expect(within(tile("Внешние сервисы")).getByText("Сбой")).toBeVisible();
    expect(within(tile("Состояние системы")).getByText("Внимание")).toBeVisible();
    for (const name of ["ERP", "Telegram", "Почта", "Хранилище и бэкапы"]) {
      expect(within(tile(name)).getByText(/Последняя проверка: \d{2}\.\d{2}\.\d{4}/)).toBeVisible();
    }
    expect(within(tile("Расходы")).getByText(/Расход сегодня: 1,60 USD/)).toBeVisible();
    // Администратору доступны «Проверить» на карточках и нет подписи «Только просмотр».
    expect(within(tile("ERP")).getByRole("button", { name: "Проверить: ERP" })).toBeEnabled();
    expect(screen.queryByText("Только просмотр")).not.toBeInTheDocument();
  });

  it("«Требует внимания»: сначала сбои, затем предупреждения; одна причина — одна строка с «с …», «Кто исправляет» и действием", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/integrations");

    const section = (
      await screen.findByRole("heading", { level: 2, name: "Требует внимания" })
    ).closest("section");
    if (!section) throw new Error("нет раздела");
    const rows = within(section).getAllByRole("listitem");
    const severities = rows.map((row) => row.getAttribute("data-severity"));
    expect(severities).toEqual([...severities].sort((a, b) => order(a) - order(b)));
    expect(severities[0]).toBe("fail");

    // OpenAI: строка вендора и две роли моделей — одна строка, а не три
    const openai = rows.filter((row) => within(row).queryByText(/Ключ OpenAI отклонён/));
    expect(openai).toHaveLength(1);
    const row = openai[0] as HTMLElement;
    expect(within(row).getByText("Сломано")).toBeVisible();
    expect(
      within(row).getByText(/не работают: поиск по базе знаний, проверка качества ответов/),
    ).toBeVisible();
    expect(within(row).getByText(/^с 26\.10\.2026/)).toBeVisible();
    expect(
      within(row).getByText("ключ и оплата — у владельца компании", { exact: false }),
    ).toBeVisible();
    // одно главное действие по смыслу и запасные
    expect(
      within(row).getByRole("button", { name: "Ввести новый ключ: Ключ OpenAI отклонён" }),
    ).toBeVisible();
    expect(within(row).getByRole("button", { name: /Написать владельцу/ })).toBeVisible();
    expect(within(row).getByRole("button", { name: /Выключить провайдера/ })).toBeVisible();
    // роли моделей отдельными строками не повторяются
    expect(within(section).queryByText("Поиск по базе знаний", { selector: "span" })).toBeNull();
    expect(within(section).queryByText(/401: ключ отклонён провайдером/)).not.toBeInTheDocument();

    const mail = rows.find((r) => within(r).queryByText("В очереди 3 письма дольше 15 минут"));
    expect(within(mail as HTMLElement).getByText("Работает с перебоями")).toBeVisible();
    // «Ожидаемо на стенде» (docling) и «Выключено намеренно» (Langfuse) в «Требует внимания» не попадают
    expect(within(section).queryByText(/Распознавание документов недоступно/)).toBeNull();
    expect(within(section).queryByText(/Langfuse/)).toBeNull();
  });

  it("клик по карточке открывает её в боковом окне (?card=)", async () => {
    signIn("admin@demo.example");
    const { router } = renderAt("/admin/integrations");
    await screen.findByRole("heading", { level: 2, name: "Сервисы" });

    fireEvent.click(within(tile("Telegram")).getByRole("link", { name: "Открыть: Telegram" }));

    expect(
      await within(await panelEl()).findByRole("heading", { level: 3, name: "Telegram" }),
    ).toBeVisible();
    expect(router.state.location.search).toContain("card=telegram");
    expect(tile("Telegram")).toHaveAttribute("data-selected", "true");
  });

  it("«Проверить» на карточке «Почта»: итог словами, сервис восстановлен — строка уходит из «Требует внимания»", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/integrations");
    expect(await screen.findByText("В очереди 3 письма дольше 15 минут")).toBeVisible();

    fireEvent.click(within(tile("Почта")).getByRole("button", { name: "Проверить: Почта" }));

    expect(await within(tile("Почта")).findByText("Проверено: Работает")).toBeVisible();
    await waitFor(() => {
      expect(within(tile("Почта")).getByText("Работает", { selector: "span" })).toBeVisible();
    });
    expect(screen.queryByText("В очереди 3 письма дольше 15 минут")).not.toBeInTheDocument();
  });

  it("сбой проверки показан словами в карточке, а не молчанием", async () => {
    signIn("admin@demo.example");
    server.use(
      http.post("*/admin/integrations/erp/check", () =>
        HttpResponse.json(
          {
            code: "INTEGRATION_FAILED",
            message: "x",
            source: "crm",
            details: { reason: "erp_unavailable" },
          },
          { status: 502 },
        ),
      ),
    );
    renderAt("/admin/integrations");
    await screen.findByRole("heading", { level: 2, name: "Сервисы" });

    fireEvent.click(within(tile("ERP")).getByRole("button", { name: "Проверить: ERP" }));

    expect(await within(tile("ERP")).findByRole("alert")).toHaveTextContent("ERP не отвечает.");
  });

  it("директор: экран открыт на чтение — «Только просмотр», ни одной кнопки проверки и изменения", async () => {
    signIn("director@demo.example");
    renderAt("/admin/integrations?card=erp&panel=open");

    expect(await screen.findByRole("heading", { level: 1, name: "Подключения" })).toBeVisible();
    expect(await screen.findByText("Только просмотр")).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Проверить/ })).not.toBeInTheDocument();
    // «Расходы» и «Состояние системы» — отчёты: директору есть «Обновить»
    expect(
      within(tile("Расходы")).getByRole("button", { name: "Обновить: Расходы" }),
    ).toBeEnabled();
    const side = await panelEl();
    expect(
      await within(side).findByText("Режим просмотра: изменения доступны администратору."),
    ).toBeVisible();
    for (const name of ["Проверить связь", "Подключить заново", "Ротация ключа"]) {
      expect(within(side).queryByRole("button", { name })).not.toBeInTheDocument();
    }
    // BFF на изменение отвечает 403 и без интерфейса
    const response = await fetch("/api/v1/admin/integrations/erp/check", {
      method: "POST",
      headers: { "X-CSRF-Token": "mock-csrf-token-0123456789abcdef" },
    });
    expect(response.status).toBe(403);
  });

  it("директор читает расходы", async () => {
    signIn("director@demo.example");
    renderAt("/admin/integrations?card=spend&panel=open");

    const side = await panelEl();
    expect(
      await within(side).findByRole("heading", { level: 4, name: "Расходы бота" }),
    ).toBeVisible();
    expect(await within(side).findByRole("table", { name: "Провайдеры за сегодня" })).toBeVisible();
    expect(
      await within(side).findByRole("heading", { level: 4, name: "Весь ансамбль" }),
    ).toBeVisible();
    expect(await within(side).findByRole("table", { name: "Расходы по группам" })).toBeVisible();
  });

  it("CRM отказала в части данных: карточка помечена, остальные работают, в панели — «Недоступно вашей роли»", async () => {
    signIn("director@demo.example");
    server.use(
      http.get("*/admin/integrations/models", () =>
        HttpResponse.json({ code: "FORBIDDEN", message: "x", source: "crm" }, { status: 403 }),
      ),
    );
    renderAt("/admin/integrations?card=models&panel=open");

    expect(await within(await panelEl()).findByText("Недоступно вашей роли")).toBeVisible();
    expect(await screen.findByRole("heading", { level: 2, name: "Сервисы" })).toBeVisible();
  });

  it("бейдж «Нет данных» не стоит рядом со строкой «Всё в порядке» (W15-G-6)", async () => {
    signIn("admin@demo.example");
    const original = await fetch("/api/v1/admin/integrations").then(
      (r) => r.json() as Promise<{ cards: Record<string, unknown>[] }>,
    );
    server.use(
      http.get("*/admin/integrations", () =>
        HttpResponse.json({
          ...original,
          cards: original.cards.map((c) =>
            c["key"] === "models" ? { ...c, status: "unknown", note: "all_ok" } : c,
          ),
        }),
      ),
    );
    renderAt("/admin/integrations");

    const models = await waitFor(() => tile("Модели ИИ"));
    expect(within(models).getByText("Нет данных", { selector: ".ant-tag" })).toBeVisible();
    expect(within(models).queryByText("Всё в порядке")).toBeNull();
    expect(within(models).getAllByText("Нет данных").length).toBeGreaterThanOrEqual(2);
  });

  it("CRM не ответила целиком: понятный текст и «Повторить»", async () => {
    signIn("admin@demo.example");
    server.use(
      http.get("*/admin/integrations", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "x", source: "crm" },
          { status: 503 },
        ),
      ),
    );
    renderAt("/admin/integrations");

    expect(await screen.findByText("Не удалось загрузить интеграции")).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});

describe("Admin · Внешние интеграции: доступ", () => {
  it("без раздела admin пункта нет в меню, а по прямому адресу — «Нет доступа»", async () => {
    signIn("manager@demo.example");
    renderAt("/admin/integrations");

    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Настройки" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Подключения" })).not.toBeInTheDocument();
  });

  it("у администратора пункт «Внешние интеграции» в подменю Admin", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/integrations");

    const menu = await screen.findByRole("navigation", { name: "Разделы модуля" });
    expect(within(menu).getByRole("link", { name: /Подключения/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});

function order(severity: string | null): number {
  return severity === "fail" ? 0 : severity === "warn" ? 1 : 2;
}
