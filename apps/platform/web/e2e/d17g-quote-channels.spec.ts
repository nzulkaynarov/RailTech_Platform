import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd, confirmDialog } from "./support/app";

// D17G-2 и D17G-3 (гейт D1-7) на MSW, 1440 и 390 px, axe WCAG 2.1 AA:
// — панель одобрения КП: каналы по фактическим контактам клиента, недоступный выключен с причиной (нет ложной тревоги);
// — после одобрения в карточке КП отчёт «Отправка клиенту»; менеджер отправляет по каналу повторно;
// — мастер «Первый запуск» и «Подключения»: «Адрес кабинета клиента» с проверкой доступности.
// Снимки — в E2E_SCREENSHOT_DIR (docs/screens/d17g), если он задан.
const WIDTHS = [1440, 390] as const;
const SETUP_KEY = "rt-pf-mock-setup";

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

async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await waitForMotionEnd(page);
  await page.waitForTimeout(400);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

/** Прокрутить к блоку: React может перерисовать его между поиском и прокруткой — повторить до успеха. */
async function scrollTo(target: Locator): Promise<void> {
  await expect(async () => {
    await target.scrollIntoViewIfNeeded({ timeout: 2000 });
  }).toPass({ timeout: 10_000 });
}

const quotePath = (number: string, query = "") =>
  `/eds/drafts/${encodeURIComponent(number)}${query}`;

test.describe("D17G: каналы отправки КП и адрес кабинета", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`директор: каналы по контакту клиента и отчёт после одобрения, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "director@demo.example");
      await spaGoto(page, quotePath("КП-2026/117", "?panel=open&tab=approve"));

      const form = page.getByRole("form", { name: "Одобрение КП" });
      await expect(form).toBeVisible();
      await expect(form.getByRole("checkbox", { name: "Почта" })).toBeDisabled();
      await expect(form.getByRole("checkbox", { name: "Почта" })).not.toBeChecked();
      await expect(form.getByText("Недоступна: нет e-mail у контакта.")).toBeVisible();
      await expect(form.getByRole("checkbox", { name: "Telegram-бот" })).toBeChecked();
      await expect(form.getByText(/Контакт клиента не получен/)).toHaveCount(0);
      await scrollTo(form.getByRole("group", { name: "Отправить клиенту через" }));
      await expectNoViolations(page, `панель одобрения ${String(width)}`);
      await shot(page, "d17g-approve-channels");

      await form.getByRole("button", { name: "Одобрить КП" }).click();

      await confirmDialog(page);
      const report = page.getByRole("list", { name: "Каналы отправки" });
      await expect(report.getByText("Telegram-бот — отправлено")).toBeVisible();
      await expect(report.getByText("Кабинет — опубликовано")).toBeVisible();
      await expect(report.getByText("Почта — не выбрано при одобрении")).toBeVisible();
      if (width === 390) {
        const close = page.getByRole("button", { name: "Закрыть" });
        if (await close.isVisible()) await close.click();
      } else {
        await page.getByRole("button", { name: "Скрыть боковое окно" }).click();
      }
      await scrollTo(report);
      await expectNoViolations(page, `отчёт по каналам ${String(width)}`);
      await shot(page, "d17g-delivery-report");
    });

    test(`менеджер: «Отправить повторно» по каналу, ${String(width)} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, quotePath("КП-2026/113", "?panel=closed"));

      const report = page.getByRole("list", { name: "Каналы отправки" });
      await expect(report.getByText("Почта — не отправлено: письмо не ушло")).toBeVisible();
      await expect(report.getByRole("button", { name: "Отправить: Telegram-бот" })).toBeVisible();
      await scrollTo(report);
      await expectNoViolations(page, `отчёт менеджера ${String(width)}`);
      await shot(page, "d17g-manager-report");

      await report.getByRole("button", { name: "Отправить повторно: Почта" }).click();
      await expect(
        report.getByText("Почта — передано почтовому сервису, итог ещё не пришёл"),
      ).toBeVisible();
      await expect(report.getByRole("button", { name: /Почта/ })).toHaveCount(0);
      await expectNoViolations(page, `после повторной отправки ${String(width)}`);
      await shot(page, "d17g-manager-resent");
    });

    test(`администратор: адрес кабинета в мастере и «Подключениях», ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      // Сервер без CABINET_DOMAIN: адреса нет нигде — шаг «Не сделано»
      const state = {
        needsAdmin: false,
        code: "",
        fresh: true,
        companyCreated: true,
        done: {},
        cabinetEnv: null,
      };
      await page.addInitScript(
        `if (!window.localStorage.getItem(${JSON.stringify(SETUP_KEY)})) window.localStorage.setItem(${JSON.stringify(SETUP_KEY)}, ${JSON.stringify(JSON.stringify(state))});`,
      );
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/setup");

      const block = page.getByRole("region", { name: "Адрес кабинета клиента" });
      await expect(block.getByText(/Адрес не задан — приглашения в кабинет/)).toBeVisible();
      await block.getByLabel("Адрес кабинета").fill("https://unreachable.example");
      await block.getByRole("button", { name: "Проверить доступность" }).click();
      await expect(block.getByText(/Адрес не открылся с сервера/)).toBeVisible();
      await scrollTo(block);
      await expectNoViolations(page, `мастер: адрес не открылся ${String(width)}`);
      await shot(page, "d17g-wizard-cabinet-unreachable");

      await block.getByLabel("Адрес кабинета").fill("https://cabinet.example.org");
      await block.getByRole("button", { name: "Проверить доступность" }).click();
      await expect(
        block.getByText("Кабинет открывается: https://cabinet.example.org."),
      ).toBeVisible();
      await block.getByRole("button", { name: "Сохранить адрес" }).click();
      await expect(
        block.getByText("Сейчас: https://cabinet.example.org (задан здесь)."),
      ).toBeVisible();
      await expectNoViolations(page, `мастер: адрес сохранён ${String(width)}`);
      await shot(page, "d17g-wizard-cabinet-saved");

      await spaGoto(page, "/admin/integrations");
      const connections = page.getByRole("region", { name: "Адрес кабинета клиента" });
      await expect(
        connections.getByText("Сейчас: https://cabinet.example.org (задан здесь)."),
      ).toBeVisible();
      await scrollTo(connections);
      await expectNoViolations(page, `подключения: адрес кабинета ${String(width)}`);
      await shot(page, "d17g-integrations-cabinet");
    });
  }
});
