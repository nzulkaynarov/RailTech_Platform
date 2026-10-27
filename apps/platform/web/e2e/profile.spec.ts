import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, openAvatarMenu, settledScreenshot, waitForMotionEnd } from "./support/app";
import { demoPhoto } from "./support/demoPhoto";

// W15-H6 на MSW: страница /me (фото, данные, Telegram сам, замещение) и «Забыли пароль?». Каждое действие — сценарием
// глазами; axe 0 и снимки 1440 и 390 (`E2E_SCREENSHOT_DIR`).
const RESET_URL = "/reset-password?token=demo-reset-token-0123456789abcdef";

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

async function openProfile(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Профиль" }).click();
  await expect(page).toHaveURL(/\/me$/);
  await expect(page.getByRole("heading", { level: 1, name: "Профиль" })).toBeVisible();
}

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

/** Весь экран одним кадром: страница длиннее окна. */
async function fullScreenshot(page: Page, name: string): Promise<void> {
  const width = page.viewportSize()?.width ?? 1440;
  await page.setViewportSize({ width, height: width <= 480 ? 2600 : 1700 });
  await settledScreenshot(page, name);
  await page.setViewportSize({ width, height: width <= 480 ? 844 : 900 });
}

test.describe("Профиль /me", () => {
  test("страница вместо окна: данные, роли словами, «Сохранить» активна при изменениях", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await openProfile(page);
    const main = page.getByRole("main");
    await expect(main).toContainText("manager@demo.example");
    await expect(main).toContainText("Менеджер по продажам");
    await expect(main).not.toContainText("Доступ");
    await expect(main).not.toContainText("CRM · ERP");

    const save = main.getByRole("button", { name: "Сохранить", exact: true });
    await expect(save).toBeDisabled();
    await main.getByRole("textbox", { name: "Телефон" }).fill("+998 90 123-45-67");
    await main
      .getByRole("textbox", { name: "Подпись для писем" })
      .fill("С уважением,\nДемо Менеджеров");
    await expect(save).toBeEnabled();
    await main.getByRole("button", { name: "Отмена", exact: true }).click();
    await expect(main.getByRole("textbox", { name: "Телефон" })).toHaveValue("");
    await expect(save).toBeDisabled();

    await main.getByRole("textbox", { name: "Имя" }).fill("Демо М. Менеджеров");
    await main.getByRole("textbox", { name: "Телефон" }).fill("+998 90 123-45-67");
    await save.click();
    await expect(page.getByText("Профиль сохранён")).toBeVisible();
    await expect(save).toBeDisabled();
    // CRM сохранила номер без пробелов; имя видно в меню аватара
    await expect(main.getByRole("textbox", { name: "Телефон" })).toHaveValue("+998901234567");
    await expect(
      page.getByRole("button", { name: /профиль и настройки, Демо М\. Менеджеров/ }),
    ).toBeVisible();
    await page.reload();
    await expect(main.getByRole("textbox", { name: "Имя" })).toHaveValue("Демо М. Менеджеров");
  });

  test("фото: выбор, обрезка по кругу, фото в рейле вместо инициалов, удаление", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await openProfile(page);
    const rail = page.getByRole("button", { name: /профиль и настройки/ });
    await expect(rail.locator("img")).toHaveCount(0);

    await page.locator('input[type="file"]').setInputFiles({
      name: "demo.png",
      mimeType: "image/png",
      buffer: demoPhoto(),
    });
    const dialog = page.getByRole("dialog", { name: "Фото профиля" });
    await expect(dialog.getByRole("group", { name: /Область фото/ })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Сохранить фото" })).toBeEnabled();
    // масштаб и сдвиг: кружок остаётся в пределах картинки
    await dialog.getByRole("slider", { name: "Масштаб" }).press("ArrowRight");
    await dialog.getByRole("group", { name: /Область фото/ }).press("ArrowLeft");
    await settledScreenshot(page, "profile-photo-crop");
    await expectNoViolations(page, "обрезка фото");
    await dialog.getByRole("button", { name: "Сохранить фото" }).click();
    await expect(page.getByText("Фото обновлено")).toBeVisible();

    await expect(rail.locator("img")).toHaveAttribute(
      "src",
      /\/api\/v1\/staff\/u-demo-manager\/avatar\?v=\d+/,
    );
    // файл отдаёт BFF (не ссылка на хранилище) и действительно картинка
    const loaded = await page.evaluate(
      `(() => { const img = document.querySelector('button[aria-label*="профиль и настройки"] img'); return Boolean(img && img.complete && img.naturalWidth === 256); })()`,
    );
    expect(loaded).toBe(true);
    await page.reload();
    await expect(
      page.getByRole("button", { name: /профиль и настройки/ }).locator("img"),
    ).toBeVisible();

    await page.getByRole("button", { name: "Удалить фото" }).click();
    await expect(page.getByText("Фото удалено")).toBeVisible();
    await expect(rail.locator("img")).toHaveCount(0);
    await expect(rail).toContainText("ДМ");
  });

  test("Telegram сам: ссылка и QR, бот подтверждает, «Привязан как @…», «Отвязать»", async ({
    page,
  }) => {
    await loginAndWait(page, "engineer@demo.example");
    await openProfile(page);
    const telegram = page.getByRole("region", { name: "Telegram для уведомлений" });
    await expect(telegram.getByText("Не привязан", { exact: true })).toBeVisible();

    await telegram.getByRole("button", { name: "Привязать Telegram" }).click();
    const dialog = page.getByRole("dialog", { name: "Привязка Telegram" });
    await expect(dialog.getByRole("img", { name: "QR-код для привязки Telegram" })).toBeVisible();
    await expect(dialog.getByRole("link", { name: "Открыть в Telegram" })).toHaveAttribute(
      "href",
      /^https:\/\/t\.me\/rt_demo_bot\?start=staff_/,
    );

    // «Нажал Start в боте»: следующий опрос профиля видит привязку и закрывает окно
    await page.evaluate(
      "window.localStorage.setItem('rt-pf-mock-tg-confirm-u-demo-engineer', 'engineer_demo')",
    );
    await expect(page.getByText("Telegram привязан", { exact: true })).toBeVisible({
      timeout: 15_000,
    });
    await expect(dialog).toBeHidden();
    await expect(telegram.getByText("Привязан как @engineer_demo")).toBeVisible();
    await expect(
      page
        .getByRole("region", { name: "Уведомления" })
        .getByRole("switch", { name: "Лиды, которые ждут меня" }),
    ).toBeEnabled();

    await telegram.getByRole("button", { name: "Отвязать" }).click();
    await page
      .getByRole("dialog", { name: "Отвязать Telegram?" })
      .getByRole("button", { name: "Отвязать" })
      .click();
    await expect(telegram.getByText("Не привязан", { exact: true })).toBeVisible();
  });

  test("замещение: заместитель видит очередь замещаемого строкой «за {имя}»", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await openProfile(page);
    const deputy = page.getByRole("region", { name: "Замещение" });
    await expect(deputy.getByText("Замещение не назначено.")).toBeVisible();

    await deputy.getByRole("combobox", { name: "Кто замещает" }).click();
    await page.getByTitle(/^Демо Менеджеров/).click();
    const today = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    const end = new Date(today.getTime() + 6 * 86_400_000);
    const fmt = (d: Date) =>
      `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${String(d.getFullYear())}`;
    await deputy.getByLabel("С даты").fill(fmt(today));
    await deputy.getByLabel("С даты").press("Enter");
    await deputy.getByLabel("По дату").fill(fmt(end));
    await deputy.getByLabel("По дату").press("Enter");
    await deputy.getByRole("button", { name: "Назначить" }).click();
    await expect(deputy.getByTestId("deputy-sentence")).toHaveText(
      `На время отсутствия мои задачи видит Демо Менеджеров с ${fmt(today)} по ${fmt(end)}.`,
    );
    await signOut(page);

    await loginAndWait(page, "manager@demo.example");
    const queue = page.getByRole("region", { name: "Что сделать сейчас" });
    await expect(queue.getByText(/^за Демо Директоров · /)).toBeVisible();
    await expect(queue.getByText("Ответить лиду L-2050")).toBeVisible();
    await settledScreenshot(page, "queue-covering");
    await openProfile(page);
    await expect(page.getByTestId("covering-list")).toContainText("Вы замещаете: Демо Директоров");
  });

  test("Telegram с QR и замещение: axe 0, снимки на 1440 и 390 @mobile", async ({ page }) => {
    await loginAndWait(page, "engineer@demo.example");
    await openProfile(page);
    const telegram = page.getByRole("region", { name: "Telegram для уведомлений" });
    await telegram.getByRole("button", { name: "Привязать Telegram" }).click();
    const dialog = page.getByRole("dialog", { name: "Привязка Telegram" });
    await expect(dialog.getByRole("img", { name: "QR-код для привязки Telegram" })).toBeVisible();
    await settledScreenshot(page, "profile-telegram-qr");
    await expectNoViolations(page, "привязка Telegram");
    await dialog.getByRole("button", { name: "Закрыть" }).click();
    await expect(dialog).toBeHidden();

    const deputy = page.getByRole("region", { name: "Замещение" });
    await deputy.scrollIntoViewIfNeeded();
    await expect(deputy.getByText("Замещение не назначено.")).toBeVisible();
    await settledScreenshot(page, "profile-deputy");
    await expectNoViolations(page, "замещение");
  });

  for (const width of [1440, 390] as const) {
    test(`страница на ${String(width)} px: без горизонтальной прокрутки, axe 0${width === 390 ? " @mobile" : ""}`, async ({
      page,
    }) => {
      test.skip(
        width === 390 && !test.info().project.name.includes("mobile"),
        "390 — проект mobile",
      );
      test.skip(width === 1440 && test.info().project.name.includes("mobile"), "1440 — десктоп");
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "admin@demo.example");
      await openProfile(page);
      await expect(page.getByRole("region", { name: "Замещение" })).toBeVisible();
      const overflow = await page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth",
      );
      expect(overflow).toBe(false);
      await expectNoViolations(page, `профиль ${String(width)}`);
      await fullScreenshot(page, "profile");
    });
  }
});

test.describe("«Забыли пароль?»", () => {
  test("со входа: форма, одинаковый ответ, путь к администратору словами", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("link", { name: "Забыли пароль?" }).click();
    await expect(page).toHaveURL(/\/forgot-password$/);
    await expect(page.getByRole("heading", { level: 1, name: "Забыли пароль?" })).toBeVisible();
    await expect(
      page.getByText("если нет ни того, ни другого — обратитесь к администратору"),
    ).toBeVisible();
    await settledScreenshot(page, "forgot-password");
    await expectNoViolations(page, "забыли пароль");

    await page.getByLabel("Электронная почта").fill("nobody@demo.example");
    await page.getByRole("button", { name: "Прислать ссылку" }).click();
    const note = page.getByRole("status");
    await expect(note).toContainText("Запрос принят");
    await expect(note).toContainText("обратитесь к администратору");
    await expect(note).not.toContainText(/не найден|нет такой/i);
    await settledScreenshot(page, "forgot-password-sent");
    await page.getByRole("link", { name: "Вернуться ко входу" }).click();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("ссылка из письма: новый пароль → вход с подсказкой; устаревшая ссылка — новая заявка", async ({
    page,
  }) => {
    await page.goto(RESET_URL);
    await expect(page.getByRole("heading", { level: 1, name: "Новый пароль" })).toBeVisible();
    await settledScreenshot(page, "reset-password");
    await expectNoViolations(page, "новый пароль");
    await page.getByLabel("Новый пароль").fill("Brand-new-secret-77");
    await page.getByLabel("Повторите пароль").fill("Brand-new-secret-77");
    await page.getByRole("button", { name: "Сохранить пароль" }).click();
    await expect(page).toHaveURL(/\/login\?reset=done$/);
    await expect(page.getByRole("status")).toContainText(
      "Пароль изменён. Войдите с новым паролем.",
    );

    await page.goto("/reset-password?token=expired-token-0123456789abcdef");
    await page.getByLabel("Новый пароль").fill("Brand-new-secret-77");
    await page.getByLabel("Повторите пароль").fill("Brand-new-secret-77");
    await page.getByRole("button", { name: "Сохранить пароль" }).click();
    await expect(page.getByRole("alert")).toContainText("Ссылка недействительна или устарела");
    await page.getByRole("link", { name: "Запросить новую ссылку" }).click();
    await expect(page).toHaveURL(/\/forgot-password$/);
  });

  test("экраны на 390 px: axe 0, без горизонтальной прокрутки @mobile", async ({ page }) => {
    for (const path of ["/forgot-password", RESET_URL]) {
      await visit(page, path);
      const overflow = await page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth",
      );
      expect(overflow).toBe(false);
      await expectNoViolations(page, path);
      await settledScreenshot(
        page,
        path.startsWith("/forgot") ? "forgot-password" : "reset-password",
      );
    }
  });
});

async function visit(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole("main")).toBeVisible();
}
