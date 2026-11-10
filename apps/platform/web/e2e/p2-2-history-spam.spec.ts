import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// W18A-P2-2 «Входящая почта: старые письма и папка Спам» на MSW. Администратор в «Подключения · Почта · Приём» находит
// папки ящика (флаг \Junk подсказывает «Спам»), сохраняет и загружает письма за 30 дней — фоном, с ходом и итогом
// «загружено N». Делопроизводитель видит письма «из истории» фильтром (не строками «Моих задач») и вкладку
// «Подозрительные»: «Не спам → в очередь». Обе ширины, axe.
const WIDTHS = [1440, 390] as const;
const MAIL_KEY = "rt-pf-mock-inbound-mail";

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
  await page.waitForTimeout(400);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

/** Вкладка списка: на 390 полоса вкладок прокручивается, поэтому — фокус и Enter, как с клавиатуры. */
async function openTab(page: Page, name: string | RegExp): Promise<void> {
  await page.getByRole("tab", { name }).focus();
  await page.keyboard.press("Enter");
}

/** Вход другим сотрудником; письма мока (`localStorage`) остаются — как в одной базе. */
async function signInAs(page: Page, email: string, width: number, fresh = false): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) {
    await page.evaluate(
      `window.localStorage.removeItem("rt-pf-mock-session");${fresh ? ` window.localStorage.removeItem("${MAIL_KEY}");` : ""}`,
    );
  }
  await loginAndWait(page, email);
}

test.describe("P2-2: старые письма и папка «Спам»", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("админ находит папки и загружает письма за период; канцелярия видит «из истории» и «Подозрительные»", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    for (const width of WIDTHS) {
      await signInAs(page, "admin@demo.example", width, true);
      await spaGoto(page, "/admin/integrations?card=mail&panel=open");
      await expect(page.getByRole("heading", { name: "Приём: общий ящик (IMAP)" })).toBeVisible();

      await page.getByRole("button", { name: "Настроить приём" }).click();
      const form = page.getByRole("form", { name: "Приём почты" });
      await form.getByRole("button", { name: "Найти папки" }).click();
      await expect(form.getByText("Найдено папок: 4")).toBeVisible();
      await expect(
        form.locator(".ant-select", { has: page.locator("#imap-spam-folder") }),
      ).toContainText("Spam");
      await shot(page, "admin-folders");
      await expectNoViolations(page, `папки ${String(width)}`);
      await form.getByLabel("Ваш пароль администратора").fill("admin-pass");
      await form.getByRole("button", { name: "Сохранить настройки" }).click();
      await expect(page.getByText("INBOX, Spam (спам)")).toBeVisible();

      await page.getByRole("button", { name: "Загрузить", exact: true }).click();
      await expect(
        page.getByText(/Загружается: \d из 3|Ищем письма в ящике/).first(),
      ).toBeVisible();
      await expect(page.getByText("Загружено новых писем: 2 из 3")).toBeVisible({
        timeout: 20_000,
      });
      await shot(page, "admin-history-done");
      await expectNoViolations(page, `загрузка ${String(width)}`);

      await signInAs(page, "registrar@demo.example", width);
      // «Задачи» — без писем «из истории».
      await expect(
        page.getByRole("link", { name: /Разобрать письмо: Акт сверки за октябрь/ }).first(),
      ).toBeVisible();
      await expect(
        page.getByRole("link", { name: /Договор поставки — подписанный экземпляр/ }),
      ).toHaveCount(0);

      await spaGoto(page, "/eds/mail");
      const queue = page.getByRole("list", { name: "Письма, ждущие разбора" });
      await expect(queue.getByRole("listitem")).toHaveCount(8);
      await page.getByText("Из истории · 2").click();
      await expect(queue.getByRole("listitem")).toHaveCount(2);
      await expect(queue.getByText("Из истории").first()).toBeVisible();
      await shot(page, "mail-history-filter");
      await expectNoViolations(page, `из истории ${String(width)}`);

      await openTab(page, "Подозрительные · 1");
      const spam = page.getByRole("list", { name: "Подозрительные письма" });
      await spam
        .getByRole("link", {
          name: "Открыть письмо «Приглашение к участию в тендере на поставку шпал»",
        })
        .click();
      await expect(page.getByRole("button", { name: "Не спам → в очередь" })).toBeVisible();
      await expect(page.getByText(/отметьте его в почте «Не спам»/)).toBeVisible();
      await shot(page, "mail-spam-card");
      await expectNoViolations(page, `подозрительное ${String(width)}`);

      await page.getByRole("button", { name: "Не спам → в очередь" }).click();
      await expect(page.getByText("Подозрительных писем нет")).toBeVisible();
      await shot(page, "mail-spam-empty");
      await openTab(page, /^Новые/);
      await expect(page.getByRole("radio", { name: /Все/ })).toBeChecked();
      await expect(
        page.getByRole("list", { name: "Письма, ждущие разбора" }).getByRole("listitem"),
      ).toHaveCount(9);
    }
  });
});
