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

test.describe("Моя очередь", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("директор: счётчики, «Что сделать сейчас», лента «Сегодня»", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    const main = page.getByRole("main");

    await expect(main.getByText(/Директор · .* · 3 решения/)).toBeVisible();
    const cards = main.getByRole("region", { name: "Счётчики очереди" }).getByRole("link");
    await expect(cards).toHaveCount(4);
    await expect(cards.nth(0)).toContainText("Входящие без резолюции");
    await expect(cards.nth(3)).toContainText("1 ждёт оплаты · 1 в отгрузке");

    const queue = main.getByRole("region", { name: "Что сделать сейчас" });
    const rows = queue.getByRole("listitem");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toContainText("срок сегодня");
    await expect(rows.nth(0)).toContainText("Наложить резолюцию на письмо ВХ-104/26");
    await expect(rows.nth(1)).toContainText("завтра");
    await expect(rows.nth(2)).toContainText("служебка");

    const panel = page.getByRole("complementary", { name: "Боковое окно" });
    await expect(panel.getByRole("tab", { name: "Сегодня", selected: true })).toBeVisible();
    await expect(panel.getByRole("listitem")).toHaveCount(4);
    await settledScreenshot(page, "dashboard-director");
  });

  test("«Открыть» ведёт на объект и открывает нужную вкладку бокового окна", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");

    await page.getByRole("link", { name: /Открыть: Одобрить КП-2026\/118/ }).click();

    await expect(page).toHaveURL(/\/eds\/drafts\/%D0%9A%D0%9F-2026%2F118\?panel=open&tab=approve$/);
    await expect(page.getByRole("tab", { name: "Одобрение", selected: true })).toBeVisible();
  });

  test("пустая очередь: слова SPEC-v3 §7.1", async ({ page }) => {
    await loginAndWait(page, "supply@demo.example");

    await expect(page.getByText("Решений от вас пока не требуется")).toBeVisible();
    await expect(
      page.getByText(
        "Новые письма приходят из CRM, черновики КП — из ERP, служебки — от сотрудников.",
      ),
    ).toBeVisible();
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
      "ERP не отвечает, данные неполные",
    );
    await expect(page.getByText("Наложить резолюцию на письмо ВХ-104/26")).toHaveCount(0);
    await settledScreenshot(page, "dashboard-erp-down");
    await expectNoViolations(page, "erp down");
  });

  test("опрос: очередь и колокольчик обновляются через 30 с и при возврате на вкладку", async ({
    page,
  }) => {
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
    const center = page.getByRole("region", { name: "Центр уведомлений" });
    await expect(center.getByRole("tab")).toHaveText([
      "Все 3",
      "Решения 2",
      "Клиенты 1",
      "Система",
    ]);
    await settledScreenshot(page, "dashboard-notifications");
    await expectNoViolations(page, "notifications popover");

    await center.getByRole("link", { name: /КП-2026\/118 ждёт вашего согласования/ }).click();

    await expect(page).toHaveURL(/\/eds\/drafts\/%D0%9A%D0%9F-2026%2F118\?panel=open&tab=approve$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Карточка КП-2026/118" }),
    ).toBeVisible();
    await expect(page.getByRole("tab", { name: "Одобрение", selected: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Центр уведомлений, 2 новых" })).toBeVisible();
    await expect(center).toHaveCount(0);
  });

  test("«Отметить все прочитанными»", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await page.getByRole("button", { name: "Центр уведомлений, 3 новых" }).click();
    const center = page.getByRole("region", { name: "Центр уведомлений" });

    await center.getByRole("button", { name: "Отметить все прочитанными" }).click();

    await expect(
      page.getByRole("button", { name: "Центр уведомлений", exact: true }),
    ).toBeVisible();
    await expect(center.getByText(/Новое:/)).toHaveCount(0);
  });

  test("вкладка «Уведомления» бокового окна и ссылка «Все уведомления»", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/crm/leads");
    await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
    await page.getByRole("link", { name: "Все уведомления" }).click();

    await expect(page).toHaveURL(/\/dashboard\/queue\?panel=open&tab=notifications$/);
    const panel = page.getByRole("complementary", { name: "Боковое окно" });
    await expect(panel.getByRole("tab", { name: "Уведомления", selected: true })).toBeVisible();
    await expect(panel.getByText("КП-2026/118 ждёт вашего согласования")).toBeVisible();
    await settledScreenshot(page, "dashboard-notifications-tab");
    await expectNoViolations(page, "notifications tab");
  });
});

test("центр уведомлений на 390: список, переход к объекту, axe", async ({ page, isMobile }) => {
  test.skip(!isMobile, "узкий экран — проект mobile");
  await loginAndWait(page, "director@demo.example");
  await page.getByRole("button", { name: "Центр уведомлений, 3 новых" }).click();
  const center = page.getByRole("region", { name: "Центр уведомлений" });
  await expect(center.getByText("КП-2026/118 ждёт вашего согласования")).toBeVisible();
  await settledScreenshot(page, "dashboard-notifications");
  await expectNoViolations(page, "notifications popover 390");

  await center.getByRole("link", { name: /КП-2026\/118 ждёт вашего согласования/ }).click();
  await expect(page).toHaveURL(/\/eds\/drafts\/%D0%9A%D0%9F-2026%2F118\?panel=open&tab=approve$/);
  await expect(page.getByRole("tab", { name: "Одобрение", selected: true })).toBeVisible();
});

test.describe("Поиск ⌘K", () => {
  test("находит сделку по номеру и открывает её", async ({ page, isMobile }) => {
    await loginAndWait(page, "manager@demo.example");
    const search = page.getByRole("combobox", { name: "Глобальный поиск" });
    if (isMobile) await search.click();
    else await page.keyboard.press("Control+k");
    await expect(search).toBeFocused();

    await search.fill("ЗВ-2026-104");

    const option = page.getByRole("option", { name: /ЗВ-2026-104 · Стрелочные приводы/ });
    await expect(option).toBeVisible();
    await expect(page.getByRole("group", { name: "CRM" })).toBeVisible();
    await settledScreenshot(page, "dashboard-search");
    await expectNoViolations(page, "search results");

    await search.press("ArrowDown");
    await search.press("Enter");
    await expect(page).toHaveURL(
      /\/crm\/requests\?request=%D0%97%D0%92-2026-104&panel=open&tab=card$/,
    );
    await expect(page.getByRole("heading", { level: 1, name: "Все заявки" })).toBeVisible();
  });

  test("группы по модулям и пустой результат", async ({ page, isMobile }) => {
    test.skip(isMobile, "достаточно десктопа");
    await loginAndWait(page, "all@demo.example");
    const search = page.getByRole("combobox", { name: "Глобальный поиск" });

    await search.fill("Демо");
    await expect(page.getByRole("group", { name: "CRM" })).toBeVisible();
    await expect(page.getByRole("group", { name: "EDS" })).toBeVisible();

    await search.fill("нет-такого");
    await expect(page.getByText("По запросу «нет-такого» ничего не найдено.")).toBeVisible();
  });
});
