import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// EDS · «Счета и оплаты» бухгалтера на MSW (D2-4): сценарий целиком — платёжка клиента на подтверждение → сверка с выпиской →
// «Подтвердить оплату» → счёт «Оплачен»; частичная оплата с видимым остатком; «Запросить платёжку»; служебка к оплате →
// «Оплачено» (дата, сумма, платёжка); менеджер читает без кнопок; снабженцу раздел закрыт; axe (WCAG 2.1 AA) на списке,
// карточке и служебках; на 390 px — карточки и лист «Оплата» на весь экран (@mobile).
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

async function openPayments(page: Page, query = ""): Promise<void> {
  await spaGoto(page, `/eds/payments${query}`);
  await expect(page.getByRole("heading", { level: 1, name: "Счета и оплаты" })).toBeVisible();
}

function row(page: Page, label: string) {
  return page.getByRole("row").filter({
    has: page.getByRole("link", { name: new RegExp(`^Показать .* ${label} в боковом окне`) }),
  });
}

const confirmForm = (page: Page) =>
  page.locator(PANEL).getByRole("form", { name: "Подтверждение оплаты" });
const memoForm = (page: Page) =>
  page.locator(PANEL).getByRole("form", { name: "Оплата служебной записки" });

test.describe("Счета и оплаты: бухгалтер", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; телефон — блок @mobile");

  test("список по вкладкам со статусами словами, числа на вкладках, поиск", async ({ page }) => {
    await loginAndWait(page, "accountant@demo.example");
    await openPayments(page);

    const nav = page.getByRole("navigation", { name: "Вкладки счетов и оплат" });
    await expect(nav.getByRole("link", { name: /^Ждут оплаты\s*2$/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(nav.getByRole("link", { name: /^К выставлению\s*1$/ })).toBeVisible();
    await expect(nav.getByRole("link", { name: /^Платёжки на подтверждение\s*1$/ })).toBeVisible();
    await expect(nav.getByRole("link", { name: /^Просрочены\s*1$/ })).toBeVisible();
    await expect(nav.getByRole("link", { name: /^Служебки к оплате\s*1$/ })).toBeVisible();

    // «Ждут оплаты»: выставленный и частично оплаченный; остаток виден
    await expect(page.getByRole("row")).toHaveCount(1 + 2);
    await expect(row(page, "СЧ-2026/142").getByText("Выставлен")).toBeVisible();
    await expect(row(page, "СЧ-2026/147").getByText("Частично оплачен")).toBeVisible();
    await expect(row(page, "СЧ-2026/147").getByText(/остаток 30\s000\s000/)).toBeVisible();
    await settledScreenshot(page, "list-awaiting");
    await expectNoViolations(page, "список: Ждут оплаты");

    await nav.getByRole("link", { name: /^Просрочены/ }).click();
    await expect(row(page, "СЧ-2026/144").getByText("Просрочен", { exact: true })).toBeVisible();
    await expect(row(page, "СЧ-2026/144").getByText("просрочен на 8 дн.")).toBeVisible();
    await settledScreenshot(page, "list-overdue");

    await nav.getByRole("link", { name: /^К выставлению/ }).click();
    await expect(row(page, "СЧ-2026/143").getByText("Не выставлен")).toBeVisible();

    await nav.getByRole("link", { name: /^Платёжки на подтверждение/ }).click();
    await expect(row(page, "СЧ-2026/145").getByText("Платёжка получена")).toBeVisible();
    await settledScreenshot(page, "list-proofs");
    await expectNoViolations(page, "список: Платёжки на подтверждение");

    await nav.getByRole("link", { name: /^Все счета/ }).click();
    await expect(page.getByRole("row")).toHaveCount(1 + 6);
    const search = page.getByRole("textbox", { name: "Поиск по номеру счёта или клиенту" });
    await search.fill("пример");
    await search.press("Enter");
    await expect(page.getByRole("row")).toHaveCount(1 + 1);
    await expect(row(page, "СЧ-2026/144")).toBeVisible();
  });

  test("платёжка клиента → сверка с выпиской → «Подтвердить оплату» → счёт «Оплачен» и ушёл с вкладки", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    await openPayments(page, "?show=proofs");

    // клик по строке — счёт в боковом окне без перехода
    await row(page, "СЧ-2026/145").getByText("ООО «Север-Путь»").click();
    const panel = page.locator(PANEL);
    await expect(panel.getByRole("heading", { level: 3, name: "СЧ-2026/145" })).toBeVisible();
    await expect(page).toHaveURL(/\/eds\/payments\?/);

    // платёжка: файл, откуда пришла, когда; «Что произойдёт»; главная кнопка
    const form = confirmForm(page);
    await expect(panel.getByText(/Откуда: Кабинет клиента/)).toBeVisible();
    await expect(
      panel.getByRole("link", { name: "Скачать платёжку платёжка-0127.pdf" }),
    ).toBeVisible();
    await expect(form.getByRole("radio", { name: "платёжка-0127.pdf" })).toBeChecked();
    await expect(form.getByLabel(/Сумма по выписке/)).toHaveValue("28000000.00");
    await expect(form.getByRole("group", { name: "Что произойдёт" })).toContainText(
      "Счёт СЧ-2026/145 станет «Оплачен»",
    );
    await expect(form.getByRole("button", { name: "Подтвердить оплату" })).toBeEnabled();
    await settledScreenshot(page, "card-proof");
    await expectNoViolations(page, "карточка счёта с платёжкой");

    await form.getByLabel("Номер операции банка").fill("BANK-8841");
    await form.getByRole("button", { name: "Подтвердить оплату" }).click();

    await expect(page.getByText(/Оплата подтверждена: 28\s000\s000/)).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Платёжек на подтверждение нет" }),
    ).toBeVisible();

    // счёт в «Все счета» — «Оплачен»
    await openPayments(page, "?show=all");
    await expect(row(page, "СЧ-2026/145").getByText("Оплачен")).toBeVisible();
    await row(page, "СЧ-2026/145")
      .getByRole("link", { name: "Открыть карточку счёта: СЧ-2026/145" })
      .click();
    await expect(page.getByRole("heading", { level: 1, name: "СЧ-2026/145" })).toBeVisible();
    const payments = page.getByRole("table", { name: "Оплаты по счёту" });
    await expect(payments.getByText("BANK-8841")).toBeVisible();
    await expect(page.getByRole("list", { name: "Журнал счёта" })).toContainText(
      "Оплата подтверждена",
    );
    await settledScreenshot(page, "card-paid");
    await expectNoViolations(page, "карточка оплаченного счёта");
  });

  test("частичная оплата: остаток виден, счёт «Частично оплачен»; сумма больше остатка — словами; затем остаток", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    await openPayments(page);
    await row(page, "СЧ-2026/142").getByText("ООО «Демо-Рейл»").click();
    const form = confirmForm(page);
    const amount = form.getByLabel(/Сумма по выписке/);
    await expect(amount).toHaveValue("112000000.00");

    // больше остатка: ответ словами, введённое остаётся
    await amount.fill("112000001.00");
    await form.getByRole("button", { name: "Подтвердить оплату" }).click();
    await expect(form.getByText(/Не сохранено: сумма больше остатка по счёту/)).toBeVisible();
    await expect(amount).toHaveValue("112000001.00");

    // «Частичная оплата»: кнопка меняет слова, «Что произойдёт» показывает остаток
    await form.getByRole("button", { name: "Частичная оплата" }).click();
    await expect(amount).toBeFocused();
    await amount.fill("40 000 000");
    const consequence = form.getByRole("group", { name: "Что произойдёт" });
    await expect(consequence).toContainText("станет «Частично оплачен»");
    await expect(consequence).toContainText(/остаток 72\s000\s000/);
    await settledScreenshot(page, "partial-form");
    await form.getByRole("button", { name: "Подтвердить частичную оплату" }).click();

    await expect(page.getByText(/Частичная оплата подтверждена/)).toBeVisible();
    await expect(row(page, "СЧ-2026/142").getByText("Частично оплачен")).toBeVisible();
    await expect(row(page, "СЧ-2026/142").getByText(/остаток 72\s000\s000/)).toBeVisible();

    // остаток закрывает счёт
    await row(page, "СЧ-2026/142").getByText("ООО «Демо-Рейл»").click();
    const next = confirmForm(page);
    await expect(next.getByLabel(/Сумма по выписке/)).toHaveValue("72000000.00");
    await next.getByRole("button", { name: "Подтвердить оплату" }).click();
    await expect(page.getByText(/Оплата подтверждена: 72\s000\s000/)).toBeVisible();
    await expect(page.getByRole("row", { name: /СЧ-2026\/142/ })).toHaveCount(0);
  });

  test("«Запросить платёжку»: шаблон сообщения клиенту и отметка; «Приложить платёжку»", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    await openPayments(page);
    await row(page, "СЧ-2026/142").getByText("ООО «Демо-Рейл»").click();
    const panel = page.locator(PANEL);

    await panel.getByRole("button", { name: "Запросить платёжку" }).click();
    await expect(panel.getByLabel("Текст сообщения")).toHaveValue(/по счёту СЧ-2026\/142 на сумму/);
    await expect(
      panel.getByText(/Автоматической отправки клиенту в бот и почту пока нет/),
    ).toBeVisible();
    await panel.getByRole("button", { name: "Отметить: платёжку запросили" }).click();
    await expect(page.getByText("Запрос платёжки отмечен в журнале счёта")).toBeVisible();
    await expect(panel.getByText(/Платёжку запросили/)).toBeVisible();
    await settledScreenshot(page, "request-proof");

    await panel.getByRole("button", { name: "Приложить платёжку" }).click();
    await panel.getByLabel("Файл платёжки").setInputFiles({
      name: "pp-142.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 demo"),
    });
    await panel.getByRole("button", { name: "Приложить", exact: true }).click();
    await expect(page.getByText("Платёжка приложена")).toBeVisible();
    await expect(panel.getByRole("link", { name: "Скачать платёжку pp-142.pdf" })).toBeVisible();
    // счёт переехал на вкладку «Платёжки на подтверждение»
    await openPayments(page, "?show=proofs");
    await expect(row(page, "СЧ-2026/142").getByText("Платёжка получена")).toBeVisible();
  });

  test("служебка к оплате → «Оплачено» (дата, сумма, платёжка) → в оплаченных", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    await openPayments(page, "?show=memos");

    const first = row(page, "СЗ-2026/015");
    await expect(first.getByText("Передана бухгалтеру")).toBeVisible();
    await expect(first.getByText("Приложен")).toBeVisible();
    await settledScreenshot(page, "memos-list");
    await expectNoViolations(page, "служебки к оплате");

    await first.getByText("Оплата командировочных расходов").click();
    const panel = page.locator(PANEL);
    await expect(panel.getByRole("heading", { level: 3, name: "СЗ-2026/015" })).toBeVisible();
    await expect(panel.getByRole("link", { name: "Скачать счёт-аренда.pdf" })).toBeVisible();
    const form = memoForm(page);
    await expect(form.getByLabel(/Сумма оплаты/)).toHaveValue("4200000.00");
    await expect(form.getByRole("group", { name: "Что произойдёт" })).toContainText(
      "станет «Оплачена»",
    );
    await form.getByLabel(/Платёжка/).setInputFiles({
      name: "pp-015.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 demo"),
    });
    await settledScreenshot(page, "memo-card");
    await expectNoViolations(page, "служебка к оплате с формой «Оплачено»");
    await form.getByRole("button", { name: "Оплачено" }).click();

    await expect(page.getByText("Служебка СЗ-2026/015 оплачена")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Служебок к оплате нет" })).toBeVisible();
    await page
      .getByRole("radiogroup", { name: "Какие служебки показать" })
      .getByText("Оплаченные")
      .click();
    await expect(row(page, "СЗ-2026/015").getByText(/Оплачена/)).toBeVisible();
    await row(page, "СЗ-2026/015")
      .getByRole("link", { name: "Открыть служебку СЗ-2026/015" })
      .click();
    await expect(page.getByRole("heading", { level: 1, name: "СЗ-2026/015" })).toBeVisible();
    await expect(page.getByRole("list", { name: "Журнал записки" })).toContainText("Оплачена");
  });
});

test.describe("Счета и оплаты: чтение и закрытые роли", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе");

  test("менеджер читает: счета ERP ему не показываются словами, служебки видны без кнопки «Оплачено»", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await openPayments(page);
    await expect(
      page.getByRole("heading", { name: "Счета клиентов вам не показываются" }),
    ).toBeVisible();
    await expectNoViolations(page, "менеджер: счета закрыты ERP");

    await page.getByRole("link", { name: /^Служебки к оплате/ }).click();
    await row(page, "СЗ-2026/015").getByText("Оплата командировочных расходов").click();
    await expect(
      page.locator(PANEL).getByRole("heading", { name: "Только просмотр" }),
    ).toBeVisible();
    await expect(memoForm(page)).toHaveCount(0);
  });

  test("снабженец: раздела «Счета и оплаты» нет — «Нет доступа»", async ({ page }) => {
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/eds/payments");
    await expect(page.getByRole("heading", { name: "Нет доступа" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Счета" })).toHaveCount(0);
    await expectNoViolations(page, "снабженец: нет доступа");
  });
});

test.describe("Счета и оплаты на телефоне @mobile", () => {
  test("@mobile список карточками; строка открывает лист «Оплата» на весь экран с кнопкой внизу", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "accountant@demo.example");
    await spaGoto(page, "/eds/payments");
    await expect(page.getByRole("list", { name: "Счета" })).toBeVisible();
    await settledScreenshot(page, "mobile-list");
    await expectNoViolations(page, "телефон: список счетов");

    await page.getByRole("link", { name: "Показать счёт СЧ-2026/142 в боковом окне" }).click();
    const sheet = page.getByRole("dialog", { name: /^Оплата/ });
    await expect(sheet.getByRole("form", { name: "Подтверждение оплаты" })).toBeVisible();
    const viewport = page.viewportSize();
    const box = await sheet.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual((viewport?.width ?? 0) - 1);
    expect(box?.height).toBeGreaterThanOrEqual((viewport?.height ?? 0) - 1);
    await expect(sheet.getByRole("button", { name: "Подтвердить оплату" })).toBeInViewport();
    await settledScreenshot(page, "mobile-card");
    await expectNoViolations(page, "телефон: лист «Оплата»");

    await sheet.getByRole("button", { name: "Закрыть" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("@mobile служебки к оплате: карточки и лист «Оплачено»", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "accountant@demo.example");
    await spaGoto(page, "/eds/payments?show=memos");
    await expect(page.getByRole("list", { name: "Служебки к оплате" })).toBeVisible();
    await settledScreenshot(page, "mobile-memos");
    await expectNoViolations(page, "телефон: служебки к оплате");

    await page.getByRole("link", { name: "Показать служебку СЗ-2026/015 в боковом окне" }).click();
    const sheet = page.getByRole("dialog", { name: /^Оплата/ });
    await expect(sheet.getByRole("form", { name: "Оплата служебной записки" })).toBeVisible();
    await expect(sheet.getByRole("button", { name: "Оплачено" })).toBeVisible();
    await settledScreenshot(page, "mobile-memo-card");
    await expectNoViolations(page, "телефон: лист «Оплачено»");
  });
});
