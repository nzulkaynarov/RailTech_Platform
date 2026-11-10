import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// Dashboard (PLT-14) на MSW: очередь и счётчики, центр уведомлений, поиск ⌘K, опрос. Скриншоты рядом с артбордом
// «v3 · 1. Dashboard» (`E2E_SCREENSHOT_DIR=<каталог>`).
async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

async function setMock(page: Page, key: string, value: string): Promise<void> {
  await page.evaluate(
    `window.localStorage.setItem(${JSON.stringify(key)}, ${JSON.stringify(value)})`,
  );
}

test.describe("Задачи", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("поток подсказок: событие шины обновляет колокольчик, бейджи и очередь без опроса", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await expect(page.getByRole("main").getByText(/Директор · .* · 8 решений/)).toBeVisible();
    // Поток подключается вместе с каркасом: ждём, пока MSW примет соединение.
    await expect
      .poll(() => page.evaluate("window.__rtMockStreamCount?.() ?? 0"), { timeout: 5_000 })
      .toBeGreaterThan(0);

    const wanted = [
      "/api/v1/queue",
      "/api/v1/queue/cards",
      "/api/v1/menu-counters",
      "/api/v1/notifications",
    ];
    const seen = new Set<string>();
    page.on("request", (request) => {
      seen.add(new URL(request.url()).pathname);
    });
    await page.evaluate(
      `window.__rtMockEmitHint?.({ topics: ["queue", "counters", "notifications"], reason: "uz.railtech.erp.quote.sent.v1" })`,
    );
    // Задержка подсказка → запросы укладывается в бюджет 2 с (слияние ≈ 0,3 с делает BFF, в моках его нет).
    await expect.poll(() => wanted.every((path) => seen.has(path)), { timeout: 2_000 }).toBe(true);
  });

  test("директор: счётчики, «Что сделать сейчас», лента «Сегодня»", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    const main = page.getByRole("main");

    // D26G-4: «Одобрить КП» — все четыре КП на шаге директора в «КП на одобрение» (EDS)
    await expect(main.getByText(/Директор · .* · 8 решений/)).toBeVisible();
    const cards = main.getByRole("region", { name: "Счётчики очереди" }).getByRole("link");
    await expect(cards).toHaveCount(4);
    await expect(cards.nth(0)).toContainText("Входящие без резолюции");
    await expect(cards.nth(3)).toContainText("1 ждёт оплаты · 1 в отгрузке");

    const queue = main.getByRole("region", { name: "Что сделать сейчас" });
    const rows = queue.getByRole("listitem");
    // D2-8: в очереди директора только решения — строк исполнения ERP нет
    await expect(rows).toHaveCount(8);
    // D2-2: просроченный заказ поставщику (erp.stock: полный) — первым
    await expect(rows.nth(0)).toContainText("Просрочен заказ");
    await expect(rows.nth(1)).toContainText("срок сегодня");
    await expect(rows.nth(1)).toContainText("Наложить резолюцию на письмо ВХ-104/26");
    // P8: требование ГНК, зарегистрированное делопроизводителем
    await expect(rows.nth(2)).toContainText("Наложить резолюцию на письмо ВХ-108/26");
    await expect(rows.nth(3)).toContainText("служебка");
    await expect(rows.nth(4)).toContainText("Одобрить КП-2026/115");
    await expect(cards.nth(1)).toContainText("КП на одобрение");
    await expect(cards.nth(1)).toContainText("4");

    // боковое окно в очереди закрыто по умолчанию (ORCHESTRATOR §3 п. 18) — «Панель» открывает «Сегодня»
    await page.getByRole("button", { name: "Показать панель", exact: true }).click();
    const panel = page.getByRole("complementary", { name: "Боковое окно" });
    await expect(panel.getByRole("tab", { name: "Сегодня", selected: true })).toBeVisible();
    await expect(panel.getByRole("listitem")).toHaveCount(4);
    await settledScreenshot(page, "dashboard-director");
  });

  test("администратор: лента «Сегодня» — слова, без служебных кодов входа (QA-P1-D-1)", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");

    await page.getByRole("button", { name: "Показать панель", exact: true }).click();
    const panel = page.getByRole("complementary", { name: "Боковое окно" });
    await expect(panel.getByRole("tab", { name: "Сегодня", selected: true })).toBeVisible();
    await expect(panel.getByRole("listitem")).toHaveCount(4);
    await expect(panel).not.toContainText(/sso\.|auth\.|login/i);
    await settledScreenshot(page, "dashboard-admin-today");
  });

  test("«Открыть» у строки с родным экраном ведёт на объект; у строки без экрана — «Где сделать»", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");

    await page
      .getByRole("link", { name: /Открыть: Наложить резолюцию на письмо ВХ-104\/26/ })
      .click();

    await expect(page).toHaveURL(/\/eds\/inbox\/%D0%92%D0%A5-104%2F26\?panel=open&tab=resolution$/);
    await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-104/26" })).toBeVisible();
  });

  test("пустая очередь: слова SPEC-v3 §7.1", async ({ page }) => {
    // у бухгалтера с D2-8 очередь не пустая (платёжка, счёт, договор) — пустая у администратора без обращений
    await loginAndWait(page, "admin@demo.example");

    await expect(page.getByText("Задач для вас нет")).toBeVisible();
    await expect(page.getByRole("main").getByText(/0 решений/)).toBeVisible();
    await settledScreenshot(page, "dashboard-empty");
    await expectNoViolations(page, "empty queue");
  });

  test("ERP не отвечает: данные CRM и плашка «ERP не отвечает, данные неполные»", async ({
    page,
  }) => {
    await loginAndWait(page, "all@demo.example");
    await setMock(page, "rt-pf-mock-erp-down", "1");
    await page.reload();

    await expect(page.getByRole("main").getByText("Взять в работу лида L-2041")).toBeVisible();
    await expect(page.getByRole("main").getByRole("status")).toContainText(
      "Не загрузились КП, расчёты, счета и проекты: раздел «Операции» не ответил. Остальное показано.",
    );
    // КП на одобрение и письмо читает EDS (D26G-4, D1-6) — строки на месте
    await expect(page.getByText("Одобрить КП-2026/118", { exact: true })).toBeVisible();
    await expect(page.getByText("Наложить резолюцию на письмо ВХ-104/26")).toBeVisible();
    await settledScreenshot(page, "dashboard-erp-down");
    await expectNoViolations(page, "erp down");
  });

  test("опрос — запасной путь при недоступном потоке: очередь и колокольчик обновляются через 30 с и при возврате на вкладку", async ({
    page,
  }) => {
    await page.addInitScript(`window.localStorage.setItem("rt-pf-mock-stream-down", "1")`);
    await page.clock.install();
    const calls: Record<string, number> = { queue: 0, notifications: 0 };
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (path === "/api/v1/queue") calls["queue"] = (calls["queue"] ?? 0) + 1;
      if (path === "/api/v1/notifications")
        calls["notifications"] = (calls["notifications"] ?? 0) + 1;
    });
    await loginAndWait(page, "director@demo.example");
    await expect.poll(() => calls["queue"]).toBeGreaterThan(0);

    const queueBefore = calls["queue"] ?? 0;
    const notificationsBefore = calls["notifications"] ?? 0;
    await page.clock.fastForward(31_000);
    await expect.poll(() => calls["queue"]).toBeGreaterThan(queueBefore);
    await expect.poll(() => calls["notifications"]).toBeGreaterThan(notificationsBefore);

    // возврат на вкладку: устаревшие данные (старше 5 с) запрашиваются снова, не дожидаясь интервала
    const queueMid = calls["queue"] ?? 0;
    await page.clock.fastForward(6_000);
    await page.evaluate(`window.dispatchEvent(new Event("visibilitychange"))`);
    await expect.poll(() => calls["queue"]).toBeGreaterThan(queueMid);
  });
});

test.describe("Центр уведомлений", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("уведомление открывает объект и нужную вкладку бокового окна, счётчик уменьшается", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await page.getByRole("button", { name: "Центр уведомлений, 3 новых" }).click();
    const center = page.getByRole("dialog", { name: "Центр уведомлений" });
    await expect(center.getByRole("radio", { name: "Непрочитанные (3)" })).toBeChecked();
    await expect(center.locator(".ant-segmented-item-label", { hasText: /^Все$/ })).toBeVisible();
    // тип — с числом непрочитанных
    await expect(center.getByRole("combobox", { name: "Тип уведомлений" })).toBeVisible();
    await center.locator(".ant-select-selector").click();
    await expect(page.locator(".ant-select-item-option")).toHaveText([
      "Все типы",
      "Решения · 2",
      "Клиенты · 1",
      "Система",
    ]);
    await page.keyboard.press("Escape");
    await settledScreenshot(page, "dashboard-notifications");
    await expectNoViolations(page, "notifications drawer");

    // Договор: у раздела «Проекты» есть экран (D2-5) — уведомление ведёт в карточку проекта на вкладку договора, счётчик уменьшается
    await center.getByRole("link", { name: /ДОГ-2026\/091/ }).click();
    await expect(page).toHaveURL(/\/eds\/projects\/.*tab=contract/);
    await expect(page.getByRole("button", { name: "Центр уведомлений, 2 новых" })).toBeVisible();
    await expectNoViolations(page, "notification opens the project");
  });

  test("с клавиатуры: Enter на колокольчике → фокус в диалоге → Tab внутри → Escape возвращает на колокольчик", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    const bell = page.getByRole("button", { name: "Центр уведомлений, 3 новых" });
    await bell.focus();
    await page.keyboard.press("Enter");

    const dialog = page.getByRole("dialog", { name: "Центр уведомлений" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("radio", { name: "Непрочитанные (3)" })).toBeFocused();

    await page.keyboard.press("Tab");
    const inside = () =>
      page.evaluate(
        `document.activeElement !== null && !!document.activeElement.closest('[role="dialog"]')`,
      );
    expect(await inside()).toBe(true);
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    expect(await inside()).toBe(true);

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("button", { name: /^Центр уведомлений/ })).toBeFocused();
  });

  test("«Отметить все прочитанными»", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await page.getByRole("button", { name: "Центр уведомлений, 3 новых" }).click();
    const center = page.getByRole("dialog", { name: "Центр уведомлений" });

    await center.getByRole("button", { name: "Отметить все прочитанными" }).click();

    await expect(
      page.getByRole("button", { name: "Центр уведомлений", exact: true }),
    ).toBeVisible();
    await expect(center.getByText(/Новое:/)).toHaveCount(0);
  });

  test("шторка не уводит с экрана: «Все» и тип фильтруют на месте; вкладка «Уведомления» в очереди", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/crm/leads");
    await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
    const center = page.getByRole("dialog", { name: "Центр уведомлений" });
    await center.locator(".ant-segmented-item-label", { hasText: /^Все$/ }).click();
    await expect(center.getByRole("combobox", { name: "Тип уведомлений" })).toBeVisible();
    await center.locator(".ant-select-selector").click();
    await page.locator(".ant-select-item-option", { hasText: "Решения" }).click();
    await expect(center.getByText("КП-2026/118 ждёт вашего согласования")).toBeVisible();
    await expect(page).toHaveURL(/\/crm\/leads$/);
    await expectNoViolations(page, "notifications filtered");
    await page.keyboard.press("Escape");

    // плоский список «Уведомления» в боковом окне очереди — по ссылке с вкладкой
    await page.goto("/dashboard/queue?panel=open&tab=notifications");
    const panel = page.getByRole("complementary", { name: "Боковое окно" });
    await expect(panel.getByRole("tab", { name: "Уведомления", selected: true })).toBeVisible();
    await expect(panel.getByText("КП-2026/118 ждёт вашего согласования")).toBeVisible();
    await settledScreenshot(page, "dashboard-notifications-tab");
    await expectNoViolations(page, "notifications tab");
  });
});

// @mobile: проект mobile (Pixel 7, 390) гоняет только сценарии с этим тегом — экраны с адаптивной логикой.
test(
  "центр уведомлений на 390: список, переход к объекту, axe",
  { tag: "@mobile" },
  async ({ page, isMobile }) => {
    test.skip(!isMobile, "узкий экран — проект mobile");
    await loginAndWait(page, "director@demo.example");
    await page.getByRole("button", { name: "Центр уведомлений, 3 новых" }).click();
    const center = page.getByRole("dialog", { name: "Центр уведомлений" });
    await expect(center.getByText("КП-2026/118 ждёт вашего согласования")).toBeVisible();
    // окно целиком внутри экрана: ни заголовок, ни вкладки, ни «Отметить все прочитанными» не обрезаны
    const viewport = page.viewportSize();
    const box = await center.boundingBox();
    expect(box).not.toBeNull();
    expect(box?.x ?? -1).toBeGreaterThanOrEqual(0);
    expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(viewport?.width ?? 0);
    const footer = await center
      .getByRole("button", { name: "Отметить все прочитанными" })
      .boundingBox();
    expect(footer?.x ?? -1).toBeGreaterThanOrEqual(0);
    await settledScreenshot(page, "dashboard-notifications");
    await expectNoViolations(page, "notifications popover 390");

    await center.getByRole("link", { name: /ДОГ-2026\/091/ }).click();
    await expect(page).toHaveURL(/\/eds\/projects\/.*(sheet|tab)=contract/);
  },
);

test.describe("Поиск ⌘K", () => {
  test(
    "находит сделку по номеру и открывает её",
    { tag: "@mobile" },
    async ({ page, isMobile }) => {
      // ЗВ открывается в «Заявках в расчёте» (B-UIA-1) — находит её роль с разделом расчёта
      await loginAndWait(page, "universal@demo.example");
      const search = page.getByRole("combobox", { name: "Глобальный поиск" });
      if (isMobile) await search.click();
      else await page.keyboard.press("Control+k");
      await expect(search).toBeFocused();

      await search.fill("ЗВ-2026-104");

      const option = page.getByRole("option", { name: /ЗВ-2026-104 · Стрелочные приводы/ });
      await expect(option).toBeVisible();
      await expect(page.getByRole("group", { name: "Контакты" })).toBeVisible();
      await settledScreenshot(page, "dashboard-search");
      await expectNoViolations(page, "search results");

      // B-UIA-1: номер ЗВ открывает заявку — «Заявки в расчёте» с окном «Задание», а не подсказку «в старом ERP»
      await search.press("ArrowDown");
      await search.press("Enter");
      await expect(page).toHaveURL(/\/erp\/requests\?request=.*tab=task/);
      await expect(page.getByRole("region", { name: "Где посмотреть" })).toHaveCount(0);
      await settledScreenshot(page, "search-request");
      await expectNoViolations(page, "search → request");
    },
  );

  test("группы по модулям и пустой результат", async ({ page, isMobile }) => {
    test.skip(isMobile, "достаточно десктопа");
    await loginAndWait(page, "all@demo.example");
    const search = page.getByRole("combobox", { name: "Глобальный поиск" });

    await search.fill("Демо");
    await expect(page.getByRole("group", { name: "Контакты" })).toBeVisible();
    await expect(page.getByRole("group", { name: "Документы" })).toBeVisible();

    await search.fill("нет-такого");
    await expect(page.getByText("По запросу «нет-такого» ничего не найдено.")).toBeVisible();
  });
});

// D26G-4 (гейт D2-6): КП ждёт одобрения директора в EDS — в «Моих задачах» строка «Одобрить КП-…» на каждое КП «на моём
// шаге» (как экран «КП на одобрение»), карточка «КП на одобрение» и бейдж меню — то же число; одобрили — строка ушла.
// Снимки — docs/screens/d26g-4 (`E2E_SCREENSHOT_DIR`).
test.describe("Задачи директора: «Одобрить КП» из EDS (D26G-4)", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of [1440, 390] as const) {
    test(`строки «Одобрить КП», карточка и экран «КП на одобрение» — одно число, ${String(width)}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      const main = page.getByRole("main");
      const rows = main
        .getByRole("region", { name: "Что сделать сейчас" })
        .getByRole("listitem")
        .filter({ hasText: /Одобрить КП-2026\// });
      await expect(rows).toHaveCount(4);
      await expect(
        main.getByRole("region", { name: "Счётчики очереди" }).getByRole("link", {
          name: /КП на одобрение/,
        }),
      ).toContainText("4");
      const dir = process.env["E2E_SCREENSHOT_DIR"];
      if (dir) {
        await waitForMotionEnd(page);
        await page.waitForTimeout(400);
        await page.screenshot({
          path: `${dir}/queue-director-quotes-${String(width)}.png`,
          fullPage: true,
        });
      }
      await expectNoViolations(page, `очередь директора ${String(width)}`);

      await rows
        .filter({ hasText: "Одобрить КП-2026/115" })
        .getByRole("link", { name: /Открыть/ })
        .click();
      await expect(page).toHaveURL(/\/eds\/drafts\/%D0%9A%D0%9F-2026%2F115\?.*tab=approve/);
      await spaGoto(page, "/eds/drafts");
      await expect(page.getByRole("heading", { level: 1, name: "КП на одобрение" })).toBeVisible();
    });
  }
});
