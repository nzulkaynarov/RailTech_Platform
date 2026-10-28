import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// «Мои задачи», поиск и колокольчик без тупиков (W15-H2, UX-оценка P0-3, P1-8, P2-9) на MSW: строка без экрана — «Где сделать»
// с мостом, строка с экраном — «Открыть» (primary у всех срочных), пустые состояния по ролям, частичный результат при отказе
// CRM или ERP, действия в поиске; axe (WCAG 2.1 AA) на каждом экране; снимки 1440 и 390 для PR (`E2E_SCREENSHOT_DIR=<каталог>`).
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

async function setMock(page: Page, key: string, value: string): Promise<void> {
  await page.evaluate(
    `window.localStorage.setItem(${JSON.stringify(key)}, ${JSON.stringify(value)})`,
  );
}

/** axe и снимок на обеих ширинах; боковое окно-Drawer на 390 закрываем, чтобы кадр показывал страницу. */
async function shoot(page: Page, name: string): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const drawer = page.getByRole("dialog", { name: "Боковое окно" });
    if (width === 390 && (await drawer.isVisible())) {
      await drawer.getByRole("button", { name: "Скрыть боковое окно" }).click();
      await expect(drawer).toBeHidden();
    }
    await expectNoViolations(page, `${name} ${String(width)}`);
    await settledScreenshot(page, name);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

test.describe("Мои задачи: «Открыть» или «Где сделать»", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("менеджер: строки без экрана — «Где сделать» с мостом в старую CRM, ссылки на заглушку нет", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    const queue = page.getByRole("region", { name: "Что сделать сейчас" });
    // у строк лидов экрана в Платформе пока нет; «Открыть» остаётся только у «Доработать» (форма «Продолжить», D1-6b)
    await expect(queue.getByRole("link", { name: /^Открыть: (Взять|Ответить)/ })).toHaveCount(0);

    await queue.getByRole("button", { name: "Где сделать: Взять в работу лида L-2041" }).click();
    const pop = page.getByRole("region", { name: "Где сделать" });
    await expect(pop.getByText(/Сейчас — в старой CRM: раздел «Лиды»/)).toBeVisible();
    const open = pop.getByRole("link", { name: /Открыть в старой CRM/ });
    await expect(open).toHaveAttribute("href", "http://crm.localhost:8088/leads/2041");
    await expect(open).toHaveAttribute("target", "_blank");
    expect(await open.getAttribute("rel")).toContain("noopener");
    await expect(pop.getByText("Когда появится: в ближайшем обновлении.")).toBeVisible();
    await shoot(page, "queue-where");
  });

  test("с клавиатуры: Enter на «Где сделать» → фокус в секции → Tab доходит до «Открыть в …» → Escape возвращает на кнопку", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    const button = page.getByRole("button", { name: "Где сделать: Взять в работу лида L-2041" });
    await button.focus();
    await page.keyboard.press("Enter");

    const panel = page.getByRole("region", { name: "Где сделать" });
    await expect(panel).toBeFocused();
    const link = panel.getByRole("link", { name: /Открыть в старой CRM/ });
    await expect(link).toBeVisible(); // адрес старой CRM приходит из BFF — Tab после его появления
    await page.keyboard.press("Tab");
    await expect(link).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(button).toBeFocused();
    await expect(button).toHaveAttribute("aria-expanded", "false");
  });

  test("директор: письмо, КП и служебка (родные экраны) — «Открыть» открывает объект с боковым окном; primary у срочных писем", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    const queue = page.getByRole("region", { name: "Что сделать сейчас" });
    const letter = queue.getByRole("link", {
      name: /Открыть: Наложить резолюцию на письмо ВХ-104/,
    });
    await expect(letter).toHaveClass(/ant-btn-primary/);
    await expect(
      queue.getByRole("link", { name: /Открыть: Одобрить КП-2026\/118/ }),
    ).not.toHaveClass(/ant-btn-primary/);
    await expect(
      queue.getByRole("link", { name: /Открыть: Согласовать СЗ-2026\/031/ }),
    ).toBeVisible();
    await settledScreenshot(page, "queue-director");

    await letter.click();
    await expect(page).toHaveURL(/\/eds\/inbox\/%D0%92%D0%A5-104%2F26\?panel=open&tab=resolution$/);
    await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-104/26" })).toBeVisible();
  });
});

test.describe("Мои задачи: пустые состояния и частичный результат", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const [email, title] of [
    ["supply@demo.example", "Заданий на расчёт нет"],
    ["engineer@demo.example", "Заданий по услугам нет"],
    ["accountant@demo.example", "Платёжек на подтверждение и счетов к выставлению нет"],
  ] as const) {
    test(`${email}: пустая очередь своими словами`, async ({ page }) => {
      await loginAndWait(page, email);
      await expect(page.getByRole("main").getByText(title)).toBeVisible();
      await expect(page.getByText("Решений от вас пока не требуется")).toHaveCount(0);
      if (email === "accountant@demo.example") await shoot(page, "queue-empty-accountant");
    });
  }

  test("ERP не отвечает: данные CRM показаны, плашка называет «Документы» и «Расчёт»", async ({
    page,
  }) => {
    await loginAndWait(page, "all@demo.example");
    await setMock(page, "rt-pf-mock-erp-down", "1");
    await page.reload();
    await expect(page.getByRole("main").getByText("Взять в работу лида L-2041")).toBeVisible();
    await expect(page.getByRole("main").getByRole("status")).toContainText(
      "Не загрузились КП на одобрение и расчёты: раздел «Расчёт» не ответил. Остальное показано.",
    );
    await shoot(page, "queue-partial-erp");
  });

  test("CRM не отвечает: данные ERP показаны, плашка называет «Клиенты»", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await setMock(page, "rt-pf-mock-crm-down", "1");
    await page.reload();
    await expect(page.getByRole("main").getByText("Одобрить КП-2026/118 (черновик)")).toBeVisible();
    await expect(page.getByRole("main").getByRole("status").first()).toContainText(
      "Не загрузились лиды и ответы клиентам: раздел «Клиенты» не ответил. Остальное показано.",
    );
    await expectNoViolations(page, "crm down");
  });
});

test.describe("Поиск: объект, «Где посмотреть», действия", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("менеджер: результат без экрана — «Где посмотреть» с мостом, адрес не меняется", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    const search = page.getByRole("combobox", { name: "Глобальный поиск" });
    await search.fill("L-2041");
    await page.getByRole("option", { name: /L-2041/ }).click();
    const where = page.getByRole("region", { name: "Где посмотреть" });
    await expect(where.getByRole("link", { name: /Открыть в старой CRM/ })).toHaveAttribute(
      "href",
      "http://crm.localhost:8088/leads/2041",
    );
    await expect(page).toHaveURL(/\/dashboard\/queue/);
    await shoot(page, "search-where");
    // Escape внутри подсказки закрывает её и возвращает фокус в поле поиска
    await where.getByRole("link", { name: /Открыть в старой CRM/ }).focus();
    await page.keyboard.press("Escape");
    await expect(where).toHaveCount(0);
    await expect(search).toBeFocused();
  });

  test("менеджер: «создать заявку» — действие в результатах; «пригласить» ему недоступно", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    const search = page.getByRole("combobox", { name: "Глобальный поиск" });
    await search.fill("создать заявку");
    const action = page.getByRole("option", { name: /Создать заявку/ });
    await expect(action).toContainText("Действие");
    await expect(page.getByRole("group", { name: "Действия" })).toBeVisible();
    await expectNoViolations(page, "search actions");
    await action.click();
    await expect(page.getByRole("region", { name: /Где посмотреть/ })).toBeVisible();

    await search.fill("пригласить");
    await expect(page.getByRole("option", { name: /Пригласить сотрудника/ })).toHaveCount(0);
  });

  test("администратор: «пригласить» ведёт в Оргструктуру с приглашением", async ({ page }) => {
    await loginAndWait(page, "admin@demo.example");
    const search = page.getByRole("combobox", { name: "Глобальный поиск" });
    await search.fill("пригласить");
    await page.getByRole("option", { name: /Пригласить сотрудника/ }).click();
    await expect(page).toHaveURL(/\/admin\/org\?invite=open&panel=open$/);
  });
});

test.describe("Колокольчик: объект без экрана", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("«Где посмотреть» раскрывается под уведомлением, окно не закрывается", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/dashboard/queue");
    await page.getByRole("button", { name: "Центр уведомлений, 3 новых" }).click();
    const center = page.getByRole("dialog", { name: "Центр уведомлений" });
    await center.getByRole("button", { name: /Где посмотреть: .*ДОГ-2026\/091/ }).click();
    await expect(
      center.getByRole("region", { name: "Где посмотреть" }).getByRole("link", {
        name: /Открыть в старом ERP/,
      }),
    ).toBeVisible();
    await shoot(page, "bell-where");
  });
});
