import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, openAvatarMenu, settledScreenshot } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-9 на MSW: доска 20 — «Мои задачи» директора с «Подписать договор / счёт», без «Зарегистрировать исходящее»;
// доска 21 — замещающий: плашка «Вы замещаете … до …», фильтр «За …», строки «за …». Снимки 1440 и 390 и axe 0
// (`E2E_SCREENSHOT_DIR`, docs/screens/sc9-final).
const WIDTHS = [1440, 390] as const;

async function at(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
}

async function noHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe("СЦ-9: подпись и замещение в «Задачах»", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`директор: строки «Подписать…» и блок подписей на ${String(width)}`, async ({ page }) => {
      await at(page, width);
      await loginAndWait(page, "director@demo.example");
      const main = page.getByRole("main");
      const contract = main.getByText("Подписать договор CT-2026-014");
      await expect(contract).toBeVisible();
      await expect(main.getByText("Подписать счёт INV-2026-031")).toBeVisible();
      await expect(main.getByText(/Зарегистрировать исходящее/)).toHaveCount(0);

      await contract
        .locator("xpath=ancestor::li[1]")
        .getByRole("link", { name: /Открыть/ })
        .click();
      await expect(page).toHaveURL(/\/dashboard\/queue\?signing=/);
      await expect(main.locator('[aria-current="true"]')).toContainText("Договор поставки");
      await settledScreenshot(page, "sign-tasks");
      await expectNoViolations(page, `sign-tasks-${String(width)}`);
      await noHorizontalScroll(page);
    });
  }

  for (const width of WIDTHS) {
    test(`замещающий: плашка, фильтр «За …» и строки «за …» на ${String(width)}`, async ({
      page,
    }) => {
      await at(page, 1440);
      await loginAndWait(page, "director@demo.example");
      await openAvatarMenu(page);
      await page.getByRole("menuitem", { name: "Профиль" }).click();
      await expect(page).toHaveURL(/\/me$/);
      const deputy = page.getByRole("region", { name: "Замещение" });
      await deputy.getByRole("combobox", { name: "Кто замещает" }).click();
      await page.getByTitle(/^Демо Менеджеров/).click();
      const pad = (n: number) => String(n).padStart(2, "0");
      const fmt = (d: Date) =>
        `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${String(d.getFullYear())}`;
      const today = new Date();
      const end = new Date(today.getTime() + 6 * 86_400_000);
      await deputy.getByLabel("С даты").fill(fmt(today));
      await deputy.getByLabel("С даты").press("Enter");
      await deputy.getByLabel("По дату").fill(fmt(end));
      await deputy.getByLabel("По дату").press("Enter");
      await deputy.getByRole("button", { name: "Назначить" }).click();
      await expect(deputy.getByTestId("deputy-sentence")).toBeVisible();
      await openAvatarMenu(page);
      await page.getByRole("menuitem", { name: "Выйти" }).click();
      await expect(page).toHaveURL(/\/login/);

      await at(page, width);
      await loginAndWait(page, "manager@demo.example");
      const main = page.getByRole("main");
      await expect(main.getByText(/Вы замещаете Демо Директоров до/)).toBeVisible();
      await expect(main.getByText(/^за Демо Директоров · /).first()).toBeVisible();
      if (width === 1440) {
        // Бейдж «Задачи» в меню равен числу строк списка, «за …» тоже (BFF считает так же)
        const decisions = (
          await main
            .getByText(/\d+ (решени|решений)/)
            .first()
            .innerText()
        ).match(/(\d+) решени/)?.[1];
        await expect(page.getByRole("link", { name: /^Задачи\s*\d+/ })).toContainText(
          String(decisions),
        );
      }
      await main.locator(".ant-segmented-item", { hasText: "За Демо Директоров" }).click();
      await expect(main.getByText("Ответить лиду L-2050")).toHaveCount(0);
      await expect(main.getByText(/^Согласовать /)).toBeVisible();
      await settledScreenshot(page, "deputy-tasks");
      await expectNoViolations(page, `deputy-tasks-${String(width)}`);
      await noHorizontalScroll(page);

      // Строка ведёт до конца: у заместителя-менеджера (раздела согласования нет) открывается форма «за …»
      await main
        .getByText(/^Согласовать /)
        .locator("xpath=ancestor::li[1]")
        .getByRole("link", { name: /Открыть/ })
        .click();
      const agree = page.getByRole("form", { name: "Согласование документа" });
      const button = agree.getByRole("button", { name: "Согласовать за Демо Директоров" });
      await expect(button).toBeVisible();
      await expect(agree.getByRole("button", { name: "Согласовать", exact: true })).toHaveCount(0);
      await expect(page.getByText(/Вы видите документ в режиме чтения/)).toHaveCount(0);
      await settledScreenshot(page, "deputy-agree");
      await expectNoViolations(page, `deputy-agree-${String(width)}`);
      await noHorizontalScroll(page);
      await button.click();
      await page
        .getByRole("dialog", { name: /^Согласовать за Демо Директоров/ })
        .getByRole("button", { name: "Согласовать за Демо Директоров" })
        .click();
      await expect(page.getByText("Документ согласован").first()).toBeVisible();
    });
  }
});
