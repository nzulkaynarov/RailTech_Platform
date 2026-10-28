import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  login,
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  waitForMotionEnd,
} from "./support/app";

// W-REL на MSW: окно «Платформа обновлена» после выкладки и отметка «Новое» у «?», «Что нового» по датам с ролями,
// «Что ожидается», «О системе» (версия, сервисы, данные для поддержки), версия внизу меню аватара, «Помогла?» и
// «Здесь устарело» под статьёй. axe 0 на 1440 и 390, без горизонтальной прокрутки (`E2E_SCREENSHOT_DIR` — снимки).

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

async function noHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

/** Вход сотрудника, который ещё не видел последнюю запись «Что нового» (сценарий мока). */
async function loginAfterRelease(page: Page, email = "director@demo.example"): Promise<void> {
  await page.goto("/login");
  await page.evaluate('window.localStorage.setItem("rt-pf-mock-whats-new", "pending")');
  await login(page, email);
  await expect(page).toHaveURL(/\/dashboard\/queue$/);
}

for (const width of [1440, 390] as const) {
  const tag = width === 390 ? " @mobile" : "";

  test.describe(`«Что нового» и «О системе», ${String(width)}${tag}`, () => {
    test.beforeEach(async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    });

    test(`после выкладки: окно один раз, «Новое» у «?», «Что нового» снимает отметку${tag}`, async ({
      page,
    }) => {
      await loginAfterRelease(page);
      const notice = page.getByRole("region", { name: "Платформа обновлена" });
      await expect(notice).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Помощь (клавиша ?), есть новое" }),
      ).toBeVisible();
      await noHorizontalScroll(page);
      await expectNoViolations(page, `окно «Платформа обновлена» ${String(width)}`);
      await settledScreenshot(page, "whats-new-notice");

      const saved = page.waitForResponse((r) => r.url().includes("/me/whats-new"));
      await notice.getByRole("button", { name: "Что нового" }).click();
      await saved;
      await expect(page).toHaveURL(/\/help\/news$/);
      await expect(
        page.getByRole("heading", { name: "Помощь, профиль и первые рабочие экраны" }),
      ).toBeVisible();
      await expect(page.getByText("Директор").first()).toBeVisible();
      await expect(page.getByRole("button", { name: "Помощь (клавиша ?)" })).toBeVisible();
      await expect(notice).toBeHidden();
      await noHorizontalScroll(page);
      await expectNoViolations(page, `«Что нового» ${String(width)}`);
      await settledScreenshot(page, "whats-new-news");

      // Перезагрузка (тот же сотрудник): окна и отметки нет — флаг хранится на сервере.
      await page.reload();
      await expect(page.getByRole("heading", { level: 1, name: "Помощь" })).toBeVisible();
      await expect(page.getByRole("region", { name: "Платформа обновлена" })).toBeHidden();
    });

    test(`«О системе»: версия, сервисы, данные для поддержки; «Что ожидается»${tag}`, async ({
      page,
    }) => {
      await loginAndWait(page, "manager@demo.example");
      await page.goto("/help/about");
      await expect(page.getByText("Платформа 2026.10.28 · 1a2b3c4").first()).toBeVisible();
      const services = page.getByRole("list", { name: "Сервисы" });
      await expect(services.getByRole("listitem")).toHaveCount(4);
      await expect(page.getByText(/^Роль: Менеджер/m)).toBeVisible();
      await noHorizontalScroll(page);
      await expectNoViolations(page, `«О системе» ${String(width)}`);
      await settledScreenshot(page, "about");

      await page.goto("/help/roadmap");
      await expect(page.getByRole("heading", { name: "Сейчас делаем" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Дальше" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Позже" })).toBeVisible();
      await noHorizontalScroll(page);
      await expectNoViolations(page, `«Что ожидается» ${String(width)}`);
      await settledScreenshot(page, "roadmap");
    });

    test(`под статьёй: «Помогла?» и «Здесь устарело» — обращение со ссылкой${tag}`, async ({
      page,
    }) => {
      await loginAndWait(page, "manager@demo.example");
      await page.goto("/help/articles/queue");
      const feedback = page.getByRole("group", { name: "Отзыв о статье" });
      await feedback.getByRole("button", { name: "Да" }).click();
      await expect(feedback.getByText("Спасибо! Рады, что помогло.")).toBeVisible();
      await expectNoViolations(page, `«Помогла?» ${String(width)}`);

      await feedback.getByRole("button", { name: "Здесь устарело" }).click();
      const dialog = page.getByRole("dialog", { name: "Написать администратору" });
      await expect(dialog.getByRole("textbox", { name: /Что случилось/ })).toHaveValue(
        /устарела: \/help\/articles\/queue/,
      );
      await expect(dialog.getByText(/версия Платформы/)).toBeVisible();
      await expectNoViolations(page, `«Здесь устарело» ${String(width)}`);
      await settledScreenshot(page, "article-outdated");
    });
  });
}

test.describe("Версия в меню аватара", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("внизу меню — «О системе» с версией; переход в помощь", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await openAvatarMenu(page);
    const item = page.getByRole("menuitem", { name: /О системе/ });
    await expect(item).toContainText("Платформа 2026.10.28 · 1a2b3c4");
    await expectNoViolations(page, "меню аватара с версией");
    await settledScreenshot(page, "avatar-version");
    await item.click();
    await expect(page).toHaveURL(/\/help\/about$/);
  });
});
