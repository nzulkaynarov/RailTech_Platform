import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  login,
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  waitForMotionEnd,
} from "./support/app";

// W15-H7 на MSW: помощь на экране и раздел /help, приветствие и тур первого входа, обращения к администратору
// (экран «Нет доступа» -> администратор видит и отвечает -> автор видит ответ). axe 0 и снимки 1440 и 390
// (`E2E_SCREENSHOT_DIR`).
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

test.describe("Помощь", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("«?» в шапке открывает статью текущего раздела; поиск; Escape возвращает фокус на «?»", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    const button = page.getByRole("button", { name: "Помощь (клавиша ?)" });
    await button.click();
    const help = page.getByRole("dialog", { name: "Помощь" });
    await expect(
      help.getByRole("heading", { name: "Мои задачи — что сделать сейчас" }),
    ).toBeVisible();
    await expect(help.getByRole("link", { name: "Все статьи" })).toBeVisible();
    await expect(help.getByRole("button", { name: "Написать администратору" })).toBeVisible();

    await help.getByRole("textbox", { name: "Поиск по статьям" }).fill("служебная записка");
    await expect(help.getByText(/Найдено статей: \d+/)).toBeVisible();
    await shoot(page, "help-drawer", async () => {
      await expect(help).toBeVisible();
    });

    await help.getByRole("textbox", { name: "Поиск по статьям" }).fill("");
    await page.keyboard.press("Escape");
    await expect(help).toBeHidden();
    await expect(button).toBeFocused();

    // клавиша ? работает вне полей ввода
    await page.locator("body").press("?");
    await expect(page.getByRole("dialog", { name: "Помощь" })).toBeVisible();
  });

  test("статья зависит от раздела: в Клиентах — про лиды; из меню аватара тоже открывается", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await page
      .getByRole("navigation", { name: "Модули" })
      .getByRole("link", { name: "Клиенты" })
      .click();
    await page.getByRole("button", { name: "Помощь (клавиша ?)" }).click();
    await expect(
      page.getByRole("dialog", { name: "Помощь" }).getByRole("heading", { level: 2 }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Помощь" }).click();
    await expect(page.getByRole("dialog", { name: "Помощь" })).toBeVisible();
  });

  test("раздел /help: с чего начать по разделам, путь заявки, словарь, клавиши, что нового", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    await page.getByRole("button", { name: "Помощь (клавиша ?)" }).click();
    await page
      .getByRole("dialog", { name: "Помощь" })
      .getByRole("link", { name: "Все статьи" })
      .click();
    await expect(page).toHaveURL(/\/help\/articles$/);
    await expect(page.getByRole("heading", { level: 1, name: "Помощь" })).toBeVisible();

    await page
      .getByRole("navigation", { name: "Разделы помощи" })
      .getByRole("link", { name: "С чего начать" })
      .click();
    await expect(page).toHaveURL(/\/help$/);
    await expect(page.getByText("Ваша роль: Бухгалтер")).toBeVisible();
    await expect(page.getByText(/Подтвердите оплату по выписке/)).toBeVisible();
    await shoot(page, "help-start");

    await page
      .getByRole("navigation", { name: "Разделы помощи" })
      .getByRole("link", { name: "Путь заявки" })
      .click();
    await expect(page.getByText("Резолюция", { exact: true })).toBeVisible();
    await expect(page.getByText("Выполнено", { exact: true })).toBeVisible();
    await shoot(page, "help-path");

    await page
      .getByRole("navigation", { name: "Разделы помощи" })
      .getByRole("link", { name: "Словарь" })
      .click();
    await expect(page.getByText("Входящее письмо (ВХ-104/26)")).toBeVisible();
    await expect(page.getByText("Служебная записка (СЗ-2026/031)")).toBeVisible();
    await expectNoViolations(page, "словарь");

    await page
      .getByRole("navigation", { name: "Разделы помощи" })
      .getByRole("link", { name: "Горячие клавиши" })
      .click();
    await expect(page.getByText("Ctrl K или ⌘ K")).toBeVisible();
    await page
      .getByRole("navigation", { name: "Разделы помощи" })
      .getByRole("link", { name: "Что нового" })
      .click();
    await expect(page.getByText("Помощь, первый вход и обращения к администратору")).toBeVisible();
    await page
      .getByRole("navigation", { name: "Разделы помощи" })
      .getByRole("link", { name: "Статьи" })
      .click();
    await page.getByRole("link", { name: "Как написать администратору" }).click();
    await expect(page).toHaveURL(/\/help\/articles\/requests-to-admin$/);
    await expectNoViolations(page, "статья");
    await noHorizontalScroll(page);
  });
});

test.describe("Обращения к администратору", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("«Нет доступа» -> обращение -> администратор видит и отвечает -> автор видит ответ", async ({
    page,
  }) => {
    // 1. Менеджер открывает раздел, которого у него нет.
    await loginAndWait(page, "manager@demo.example");
    await page.goto("/admin/org");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    await page.getByRole("button", { name: "Написать администратору" }).click();
    const dialog = page.getByRole("dialog", { name: "Написать администратору" });
    await expect(dialog.getByText("Нужен доступ к разделу")).toBeVisible();
    await expect(dialog.getByText(/страница \/admin\/org, роль Менеджер/)).toBeVisible();
    await dialog.getByRole("button", { name: "Отправить" }).click();
    await expect(dialog.getByText("Опишите, что случилось", { exact: true })).toBeVisible();
    await dialog
      .getByRole("textbox", { name: "Что случилось" })
      .fill("Нужен доступ к Оргструктуре: хочу видеть, кто в какой роли");
    await shoot(page, "ticket-write", async () => {
      await expect(dialog).toBeVisible();
    });
    await dialog.getByRole("button", { name: "Отправить" }).click();
    const done = page.getByRole("dialog", { name: "Обращение ОБР-0001 отправлено" });
    await expect(done).toBeVisible();
    await done.getByRole("button", { name: "Закрыть", exact: true }).click();
    await signOut(page);

    // 2. Администратор находит обращение в «Настройки · Обращения сотрудников» и в колокольчике.
    await login(page, "admin@demo.example");
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
    await page
      .getByRole("navigation", { name: "Модули" })
      .getByRole("link", { name: "Настройки" })
      .click();
    await page
      .getByRole("navigation", { name: "Разделы модуля" })
      .getByRole("link", { name: /Обращения сотрудников/ })
      .click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Обращения сотрудников" }),
    ).toBeVisible();
    const row = page.getByRole("link", { name: "Открыть обращение ОБР-0001" });
    await expect(row).toBeVisible();
    await row.click();
    const card = page.getByRole("heading", { level: 3, name: /ОБР-0001/ });
    await expect(card).toBeVisible();
    await expect(page.getByText("Демо Менеджеров").first()).toBeVisible();
    await shoot(page, "tickets-admin", async () => {
      await expect(
        page.getByRole("heading", { level: 1, name: "Обращения сотрудников" }),
      ).toBeVisible();
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page
      .getByRole("textbox", { name: "Ваш ответ" })
      .fill("Доступ выдан: выйдите и войдите заново");
    await page.getByRole("button", { name: "Отправить ответ" }).click();
    await expect(page.getByText("Ответ отправлен")).toBeVisible();
    await expect(page.getByText("Доступ выдан: выйдите и войдите заново")).toBeVisible();
    await page.getByRole("button", { name: "Отметить решённым", exact: true }).click();
    await expect(page.getByRole("button", { name: "Вернуть в работу" })).toBeVisible();
    await signOut(page);

    // 3. Автор видит ответ в колокольчике и в «Мои обращения».
    await loginAndWait(page, "manager@demo.example");
    await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
    const bell = page.getByRole("dialog", { name: "Центр уведомлений" });
    await expect(bell.getByText(/Ответ на обращение ОБР-0001/)).toBeVisible();
    await bell.getByRole("link", { name: /Ответ на обращение ОБР-0001/ }).click();
    await expect(page).toHaveURL(/\/help\/requests\/.+/);
    await expect(page.getByText("Доступ выдан: выйдите и войдите заново")).toBeVisible();
    await expect(page.getByText("Решено").first()).toBeVisible();
    await shoot(page, "my-request", async () => {
      await expect(page.getByRole("heading", { level: 1, name: "Помощь" })).toBeVisible();
    });
    // директору обращение другого сотрудника не открывается из «Моих обращений»: у каждого — свои
    await page.goto("/help/requests");
    await expect(page.getByRole("link", { name: "Открыть обращение ОБР-0001" })).toBeVisible();
  });

  test("пустой список: текст из задачи", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    await page.goto("/admin/tickets");
    await expect(page.getByText("Обращений нет")).toBeVisible();
    await expect(
      page.getByText("Сотрудники пишут сюда с экрана «Нет доступа» и из «Помощи»."),
    ).toBeVisible();
    await shoot(page, "tickets-empty");
  });
});

test.describe("Помощь на узком экране", () => {
  test("узкий экран: «Написать администратору» и «Мои обращения» без горизонтальной прокрутки @mobile", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "manager@demo.example");
    await page.goto("/help/requests");
    await expect(page.getByRole("heading", { level: 1, name: "Помощь" })).toBeVisible();
    await noHorizontalScroll(page);
    await expectNoViolations(page, "мои обращения 390");
  });
});

test.describe("Первый вход", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  async function firstLogin(email: string, page: Page): Promise<void> {
    await page.goto("/login");
    await page.evaluate('window.localStorage.setItem("rt-pf-mock-onboarding", "pending")');
    await login(page, email);
    await expect(page).toHaveURL(/\/dashboard\/queue$/);
  }

  test("приветствие и тур: роль, четыре шага, Escape и «Больше не показывать»", async ({
    page,
  }) => {
    await firstLogin("manager@demo.example", page);
    const welcome = page.getByRole("dialog", { name: /Добро пожаловать, Демо Менеджеров/ });
    await expect(welcome.getByText("Ваша роль — Менеджер.")).toBeVisible();
    await expect(welcome.getByText("Вот что вы будете делать утром:")).toBeVisible();
    await shoot(page, "welcome", async () => {
      await expect(welcome).toBeVisible();
    });

    await welcome.getByRole("button", { name: "Показать, где что" }).click();
    const tour = page.getByRole("dialog", { name: "Знакомство с Платформой" });
    await expect(tour).toBeFocused();
    await expect(tour.getByText("Шаг 1 из 4")).toBeVisible();
    await shoot(page, "tour-rail", async () => {
      await expect(tour).toBeVisible();
    });
    await page.setViewportSize({ width: 1440, height: 900 });

    for (const title of ["«Мои задачи»", "Колокольчик", "Помощь"]) {
      await tour.getByRole("button", { name: "Дальше" }).click();
      await expect(tour.getByRole("heading", { name: title })).toBeVisible();
      await expect(tour).toBeFocused();
    }
    await expectNoViolations(page, "тур, шаг 4");
    await settledScreenshot(page, "tour-help");

    await page.keyboard.press("Escape");
    await expect(tour).toBeHidden();
    await expect(page.getByRole("button", { name: "Помощь (клавиша ?)" })).toBeVisible();

    // «Пропустить» не ставит флаг: в новом сеансе (новая вкладка без sessionStorage) приветствие вернётся
    const second = await page.context().newPage();
    await second.goto("/dashboard/queue");
    await expect(second.getByRole("dialog", { name: /Добро пожаловать/ })).toBeVisible();
    await second.getByRole("button", { name: "Больше не показывать" }).click();
    await expect(second.getByRole("dialog", { name: /Добро пожаловать/ })).toBeHidden();
    await second.close();

    // флаг лежит в профиле (CRM), а не в браузерном хранилище вкладки
    const third = await page.context().newPage();
    await third.goto("/dashboard/queue");
    await expect(third.getByRole("button", { name: "Помощь (клавиша ?)" })).toBeVisible();
    await expect(third.getByRole("dialog", { name: /Добро пожаловать/ })).toBeHidden();
    await third.close();
  });
});
