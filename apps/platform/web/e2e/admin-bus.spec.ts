import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption } from "./support/fields";

// Admin · Журнал интеграций на MSW (W13-A2): подписчики трёх доменов с состоянием словом, «Повторить все dead» с «Что
// произойдёт», DLQ и «Повторить доставку», доставки с фильтрами, входящие с ошибками и «Повторить обработку»; директору и
// менеджеру — нет пункта и «Нет доступа»; axe (WCAG 2.1 AA) на каждом разделе и в боковом окне; снимки 1440 и 390 для PR.
const WIDTHS = [1440, 390] as const;
const PANEL = "#pf-context-panel";

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

async function openJournal(page: Page, view?: string): Promise<void> {
  await spaGoto(page, view ? `/admin/bus?view=${view}` : "/admin/bus");
  // один «Журнал» (W15-H4): обмен между системами — его фильтр
  await expect(page.getByRole("heading", { level: 1, name: "Журнал" })).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Что показать в журнале" })
      .getByRole("link", { name: "Обмен между системами" }),
  ).toHaveAttribute("aria-current", "page");
}

function side(page: Page): Locator {
  return page.locator(PANEL);
}

function domainCard(page: Page, domain: string): Locator {
  return page.getByRole("region", { name: `${domain} отправляет` });
}

/** Скриншот высокого окна: блок «Что произойдёт» и итог лежат ниже первого экрана панели. */
async function tallScreenshot(page: Page, name: string): Promise<void> {
  const width = page.viewportSize()?.width ?? 1440;
  await page.setViewportSize({ width, height: 1400 });
  await settledScreenshot(page, name);
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
}

test.describe("Журнал интеграций: администратор", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; ширины проверяет блок axe");

  test("подписчики трёх доменов: состояние словом, пауза предохранителя, счётчики", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openJournal(page);
    const crm = domainCard(page, "CRM");
    await expect(crm.getByRole("row", { name: /ERP .*Есть недоставленные/ })).toBeVisible();
    await expect(crm.getByRole("row", { name: /Платформа .*Ошибки подряд/ })).toBeVisible();
    const erp = domainCard(page, "ERP");
    await expect(erp.getByRole("row", { name: /CRM .*Пауза до \d{2}:\d{2}/ })).toBeVisible();
    await expect(
      domainCard(page, "EDS").getByRole("row", { name: /Платформа .*Выключен/ }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: /Недоставлено \(DLQ\)\s*4/ })).toBeVisible();
    await settledScreenshot(page, "subscribers");
  });

  test("«Повторить все dead» подписчика: «Что произойдёт», повтор, подписчик снова «Работает»", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openJournal(page);
    await domainCard(page, "CRM")
      .getByRole("button", { name: "Повторить все dead: ERP (CRM)" })
      .click();
    const panel = side(page);
    await expect(
      panel.getByRole("heading", { name: "Повторить все недоставленные · ERP" }),
    ).toBeVisible();
    const consequence = panel.getByRole("group", { name: "Что произойдёт" });
    await expect(consequence.getByText(/Все доставки этого подписчика из DLQ \(3\)/)).toBeVisible();
    await expect(consequence.getByText(/Сначала исправьте причину/)).toBeVisible();
    await tallScreenshot(page, "retry-dead");

    await panel.getByRole("button", { name: "Повторить 3" }).click();
    await expect(panel.getByText("Поставлены на повтор 3 доставки.")).toBeVisible();
    await expect(
      domainCard(page, "CRM").getByRole("row", { name: /ERP .*Работает/ }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: /Недоставлено \(DLQ\)\s*1/ })).toBeVisible();
    await tallScreenshot(page, "retry-dead-done");
  });

  test("DLQ: недоставленные всех доменов, «Повторить доставку» в боковом окне", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await openJournal(page, "dlq");
    const table = page.getByRole("table", { name: "Недоставленные события (DLQ)" });
    await expect(table.getByText("Не доставлено")).toHaveCount(4);
    await settledScreenshot(page, "dlq");

    await table.getByRole("button", { name: "Подробнее: erp.invoice.issued → CRM" }).click();
    const panel = side(page);
    await expect(panel.getByText("uz.railtech.erp.invoice.issued.v1")).toBeVisible();
    await expect(panel.getByText("HTTP 422: payload.amount is not a string")).toBeVisible();
    await expect(panel.getByText(/Тело события в журнал не выводится/)).toBeVisible();
    await tallScreenshot(page, "dlq-delivery");
    await panel.getByRole("button", { name: /Повторить доставку/ }).click();
    await expect(panel.getByText(/Поставлено на повтор/)).toBeVisible();
    await expect(table.getByText("Не доставлено")).toHaveCount(3);
  });

  test("доставки: фильтр по домену, статусу и типу; пустой результат и сброс", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await openJournal(page, "deliveries");
    const table = page.getByRole("table", { name: "Доставки событий подписчикам" });
    await expect(table.getByRole("row")).toHaveCount(12);

    await chooseOption(page.getByLabel("Домен"), "ERP");
    await expect(table.getByRole("row")).toHaveCount(5);
    await page.getByLabel("Тип события содержит").fill("quote");
    await expect(table.getByRole("row")).toHaveCount(2);
    await expect(table.getByText("Ждёт повтора")).toBeVisible();
    await settledScreenshot(page, "deliveries-filtered");

    await page.getByLabel("Тип события содержит").fill("nothing-like-this");
    await expect(page.getByRole("heading", { name: "Доставок не найдено" })).toBeVisible();
    await page.getByRole("button", { name: "Сбросить фильтры" }).first().click();
    await expect(
      page.getByRole("table", { name: "Доставки событий подписчикам" }).getByRole("row"),
    ).toHaveCount(12);
  });

  test("входящие с ошибками: «Повторить обработку» убирает запись", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await openJournal(page, "inbox");
    const table = page.getByRole("table", { name: "Принятые события, обработка которых упала" });
    await expect(table.getByRole("row")).toHaveCount(4);
    await table.getByRole("button", { name: "Подробнее: erp.deal.won в CRM" }).click();
    const panel = side(page);
    await expect(panel.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await tallScreenshot(page, "inbox-entry");
    await panel.getByRole("button", { name: "Повторить обработку" }).click();
    await expect(panel.getByText(/Поставлено на повтор/)).toBeVisible();
    await expect(table.getByRole("row")).toHaveCount(3);
    await settledScreenshot(page, "inbox-after-retry");
  });
});

test.describe("Журнал интеграций: права", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе");

  for (const email of ["director@demo.example", "manager@demo.example"]) {
    test(`${email}: пункта нет, прямой адрес — «Нет доступа», BFF — 403`, async ({ page }) => {
      await loginAndWait(page, email);
      await page.goto("/admin/bus");
      await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
      await expect(page.getByRole("link", { name: "Обмен между системами" })).toHaveCount(0);
      const status = await page.evaluate<number>(`(async () => {
        const response = await fetch("/api/v1/admin/bus");
        return response.status;
      })()`);
      expect(status).toBe(403);
      if (email.startsWith("director")) await settledScreenshot(page, "director-forbidden");
    });
  }
});

test.describe("Журнал интеграций: axe и снимки", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`администратор на ${String(width)}: все разделы и боковое окно без нарушений axe`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");

      await openJournal(page);
      await expect(page.getByRole("heading", { level: 3, name: "CRM отправляет" })).toBeVisible();
      await expectNoViolations(page, `subscribers ${String(width)}`);
      await settledScreenshot(page, "a11y-subscribers");

      await page.getByRole("button", { name: "Повторить все dead: ERP (CRM)" }).click();
      await expect(side(page).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
      await expectNoViolations(page, `retry-dead ${String(width)}`);
      await settledScreenshot(page, "a11y-retry-dead");

      for (const view of ["deliveries", "dlq", "inbox"] as const) {
        await openJournal(page, view);
        // 1440 — таблица, 390 — список строк
        await expect(page.locator(".pf-bus table, .pf-bus ul.pf-bus-list").first()).toBeVisible();
        await expect(page.locator(".ant-skeleton, [data-pf-skeleton]")).toHaveCount(0);
        await expectNoViolations(page, `${view} ${String(width)}`);
        await settledScreenshot(page, `a11y-${view}`);
      }

      await openJournal(page, "dlq");
      await page.getByRole("button", { name: "Подробнее: erp.invoice.issued → CRM" }).click();
      await expect(side(page).getByRole("group", { name: "Что произойдёт" })).toBeVisible();
      await expectNoViolations(page, `delivery panel ${String(width)}`);
      await settledScreenshot(page, "a11y-delivery-panel");
    });
  }
});
