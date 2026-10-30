import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  login,
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  waitForMotionEnd,
} from "./support/app";

// W18A-P5 на MSW: Настройки · Статьи компании (список, редактор с предпросмотром, публикация, удаление) и «Как у нас принято»
// в Помощи (окно и страница, общий поиск). axe 0 и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR`).
const WIDTHS = [1440, 390] as const;

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

/** axe и снимок на 1440 и 390; потом окно возвращается к 1440. */
async function shoot(page: Page, name: string, prepare?: () => Promise<void>): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    if (prepare) await prepare();
    await expectNoViolations(page, `${name} ${String(width)}`);
    await settledScreenshot(page, name);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

async function noHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe("Статьи компании", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("администратор пишет и публикует статью, сотрудник находит её в Помощи", async ({
    page,
  }) => {
    // 1. Администратор открывает раздел из меню Настроек.
    await loginAndWait(page, "admin@demo.example");
    await page
      .getByRole("navigation", { name: "Модули" })
      .getByRole("link", { name: "Настройки" })
      .click();
    await page
      .getByRole("navigation", { name: "Разделы модуля" })
      .getByRole("link", { name: "Статьи компании" })
      .click();
    await expect(page).toHaveURL(/\/admin\/articles/);
    await expect(page.getByRole("heading", { level: 1, name: "Статьи компании" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Кто согласует договор", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Черновик").first()).toBeVisible();
    await shoot(page, "articles-list", async () => {
      await expect(
        page.getByRole("button", { name: "Кто согласует договор", exact: true }),
      ).toBeVisible();
    });

    // 2. Новая статья: пустое не уходит, предпросмотр показывает разметку, HTML остаётся текстом.
    await page.getByRole("button", { name: "Новая статья" }).click();
    await expect(page.getByRole("button", { name: "Сохранить черновик" })).toBeHidden();
    await page.getByRole("button", { name: "Сохранить и опубликовать" }).click();
    await expect(page.getByText("Напишите заголовок.", { exact: true })).toBeVisible();
    await page.getByRole("textbox", { name: "Заголовок" }).fill("Как оформить командировку");
    await page
      .getByRole("textbox", { name: "Текст статьи" })
      .fill(
        "## Шаги\n\n- заявка директору\n- билеты через бухгалтера\n\n<script>alert(1)</script> остаётся текстом",
      );
    const preview = page.getByRole("region", { name: "Так статья выглядит в Помощи" });
    await expect(preview.getByRole("heading", { name: "Шаги" })).toBeVisible();
    await expect(preview.getByText("<script>alert(1)</script> остаётся текстом")).toBeVisible();
    await expect(preview.locator("script")).toHaveCount(0);
    await shoot(page, "articles-editor", async () => {
      await expect(preview).toBeVisible();
    });
    await page.getByRole("button", { name: "Сохранить и опубликовать" }).click();
    await expect(
      page.getByText("Статья опубликована: теперь её видят все сотрудники."),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Как оформить командировку", exact: true }),
    ).toBeVisible();
    await signOut(page);

    // 3. Сотрудник видит статью в окне «?» и на странице «Помощь», общий поиск находит и её, и статьи Платформы.
    await login(page, "manager@demo.example");
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
    // «Контакты»: статьи к этому разделу нет, в окне видны статьи Платформы и «Как у нас принято».
    await page.goto("/chats/contacts");
    await page.getByRole("button", { name: "Помощь (клавиша ?)" }).click();
    const help = page.getByRole("dialog", { name: "Помощь" });
    await help.getByRole("textbox", { name: "Поиск по статьям" }).fill("командировку");
    await expect(
      help.getByRole("button", { name: "Как оформить командировку", exact: true }),
    ).toBeVisible();
    await help.getByRole("textbox", { name: "Поиск по статьям" }).fill("");
    await shoot(page, "help-company-drawer", async () => {
      await expect(help.getByRole("region", { name: "Как у нас принято" })).toBeVisible();
    });
    await help.getByRole("link", { name: "Все статьи" }).click();
    await expect(page).toHaveURL(/\/help\/articles$/);
    const company = page.getByRole("region", { name: "Как у нас принято" });
    await expect(company.getByRole("link", { name: "Как оформить командировку" })).toBeVisible();
    await expect(company.getByText("График отпусков")).toHaveCount(0);
    await shoot(page, "help-company-articles", async () => {
      await expect(company).toBeVisible();
    });

    await page.getByRole("textbox", { name: "Поиск по статьям" }).fill("договор");
    await expect(page.getByRole("link", { name: "Кто согласует договор" })).toBeVisible();
    await page.getByRole("textbox", { name: "Поиск по статьям" }).fill("резолюция");
    await expect(page.getByRole("link", { name: /Входящие письма/ })).toBeVisible();
    await page.getByRole("textbox", { name: "Поиск по статьям" }).fill("");
    await company.getByRole("link", { name: "Кто согласует договор" }).click();
    await expect(page).toHaveURL(/\/help\/articles\/company-1$/);
    await expect(
      page.getByRole("heading", { level: 2, name: "Кто согласует договор" }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Порядок согласования" })).toBeVisible();
    await expectNoViolations(page, "статья компании");
    await noHorizontalScroll(page);
  });

  test("удаление: подтверждение, потом статья пропадает из Помощи; директор читает без кнопок записи", async ({
    page,
  }) => {
    await loginAndWait(page, "admin@demo.example");
    await page.goto("/admin/articles");
    const row = page.getByRole("row", { name: /Где лежат шаблоны писем/ });
    await row.getByRole("button", { name: "Удалить: Где лежат шаблоны писем" }).click();
    const dialog = page.getByRole("dialog", { name: "Удалить статью?" });
    await expect(dialog).toContainText("будет удалена насовсем");
    await shoot(page, "articles-delete", async () => {
      await expect(dialog).toBeVisible();
    });
    await dialog.getByRole("button", { name: "Удалить" }).click();
    await expect(page.getByText("Статья удалена.")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Где лежат шаблоны писем", exact: true }),
    ).toHaveCount(0);
    await signOut(page);

    await login(page, "director@demo.example");
    await page.goto("/admin/articles");
    await expect(page.getByRole("heading", { level: 1, name: "Статьи компании" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Новая статья" })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "График отпусков на следующий год", exact: true }),
    ).toBeVisible();
    await expectNoViolations(page, "директор читает");
  });
});
