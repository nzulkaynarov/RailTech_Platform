import { type Page, expect, test } from "@playwright/test";

import { expectNoViolations } from "./support/axe";
import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";

// РАСЧ-1 на MSW: закупка строки подписана «цена партнёра … от … действует до …»; другую цену выбирают из короткого списка,
// после чего закупка и валюта строки меняются; снимки 1440 и 390, axe без нарушений.
const NUMBER = "ЗВ-2026-097";
// Телефон первым: на 1440 сценарий меняет выбранную цену.
const WIDTHS = [390, 1440] as const;

/** Таблица шире окна и прокручивается внутри: для снимка двигаем её к колонке закупки. */
async function showPurchaseColumn(page: Page): Promise<void> {
  await page.getByTestId("partner-source").first().scrollIntoViewIfNeeded();
  await page.evaluate(
    `document.querySelectorAll(".pf-fp-scroll").forEach((region) => { region.scrollLeft = region.scrollWidth; })`,
  );
}

test("закупка берёт цену партнёра, другую цену выбирают из списка", async ({ page }) => {
  await loginAndWait(page, "supply@demo.example");
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await spaGoto(page, `/erp/calc/${encodeURIComponent(NUMBER)}`);
    await expect(
      page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
    ).toBeVisible();

    const source = page.getByTestId("partner-source").first();
    await expect(source).toContainText("ООО «Вымышленная Сталь»");
    await expect(source).toContainText("до 31.12.2026");
    await showPurchaseColumn(page);
    await settledScreenshot(page, `partner-price-${String(width)}`);
    await expectNoViolations(page, `расчёт с ценой партнёра, ${String(width)} px`);

    if (width === 1440) {
      await page.getByTestId("partner-source").first().getByRole("button").click();
      await page.getByRole("option", { name: /ООО «Демо Металл» · / }).click();
      await expect(page.getByTestId("partner-source").first()).toContainText("ООО «Демо Металл»");
      await showPurchaseColumn(page);
      await settledScreenshot(page, "partner-price-picked-1440");
    }
  }
});

// Реалистичный расчёт: 12 строк, два партнёра в разных валютах, истёкшая цена, строка без цены, маржа ниже порога —
// предупреждение рядом с «Расчёт готов», сама кнопка не заблокирована предупреждением.
test("расчёт на 12 строк: цены партнёров, истёкшая и отсутствующая цена, предупреждение о марже", async ({
  page,
}) => {
  await loginAndWait(page, "supply@demo.example");
  for (const [width, height] of [
    [1512, 982],
    [1280, 800],
    [390, 844],
  ] as const) {
    await page.setViewportSize({ width, height });
    await spaGoto(page, `/erp/calc/${encodeURIComponent("ЗВ-2026-121")}`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Расчёт по заявке ЗВ-2026-121" }),
    ).toBeVisible();
    await expect(page.getByTestId("partner-source").first()).toContainText("до 31.12.2026");
    await expect(page.getByRole("status").filter({ hasText: "ниже порога" })).toBeVisible();
    if (width >= 1280) {
      // Стандарт владельца: на 1512 и 1280 таблица строк не прокручивается вбок
      const overflow = await page.evaluate(
        `Array.from(document.querySelectorAll(".pf-fp-scroll")).some((el) => el.scrollWidth > el.clientWidth + 1)`,
      );
      expect(overflow, `горизонтальная прокрутка таблицы на ${String(width)} px`).toBe(false);
    }
    await settledScreenshot(page, `wide-${String(width)}`);
    await page.getByTestId("partner-source").first().scrollIntoViewIfNeeded();
    await settledScreenshot(page, `wide-prices-${String(width)}`);
    await page.getByRole("status").filter({ hasText: "ниже порога" }).scrollIntoViewIfNeeded();
    await settledScreenshot(page, `wide-ready-${String(width)}`);
    await expectNoViolations(page, `расчёт на 12 строк, ${String(width)} px`);
  }
});

// РАСЧ-3 на MSW: цена строк считается от маржи сама, введённая вручную помечена и возвращается к марже одной кнопкой.
test("цена от маржи: правило под таблицей, «Цена вручную» и «вернуть N %»", async ({ page }) => {
  await loginAndWait(page, "supply@demo.example");
  await page.setViewportSize({ width: 1512, height: 982 });
  await spaGoto(page, `/erp/calc/${encodeURIComponent("ЗВ-2026-121")}`);
  await expect(page.getByTestId("price-rule")).toContainText("маржа 20 %");
  await expect(page.getByTestId("price-rule")).toContainText("до 1");
  await expect(page.getByTestId("price-manual")).toHaveCount(1);

  // Закупка в долларах: 4 000 USD × 12 100 = 48 400 000 → /0,8 = 60 500 000
  const cable = "Кабель силовой медный с изоляцией из сшитого полиэтилена 3×95+1×50, барабан 500 м";
  await expect(page.getByLabel(`Цена клиенту без НДС за единицу для «${cable}»`)).toHaveValue(
    /60\s500\s000/,
  );

  // Закупка выросла — цена от маржи следует за ней сама, без правки цены
  const purchase = page.getByLabel(`Закупка за единицу для «${cable}»`);
  await purchase.fill("5000");
  await purchase.blur();
  await expect(page.getByLabel(`Цена клиенту без НДС за единицу для «${cable}»`)).toHaveValue(
    /75\s625\s000/,
  );

  await page.getByTestId("price-manual").getByRole("button").click();
  await expect(page.getByTestId("price-manual")).toHaveCount(0);
});
