import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// EDS · «КП на одобрение» и «На согласовании» на MSW (D1-4): сценарий директора целиком — КП на одобрение → карточка → «Одобрить
// КП → отправить клиенту» (каналы) → в «Моём шаге» его больше нет; КП с незелёным чек-листом — кнопка неактивна с подписью;
// «Вернуть на доработку»; служебка → «Согласовать», «Отклонить» с комментарием; менеджер видит КП без маржи и без кнопок решения;
// axe (WCAG 2.1 AA); на 390 px «Одобрение» и «Согласование» — лист на весь экран с кнопками внизу (@mobile).
const PANEL = "#pf-context-panel";
const APPROVE = "Одобрить КП → отправить клиенту";

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

async function openDrafts(page: Page, query = ""): Promise<void> {
  await spaGoto(page, `/eds/drafts${query}`);
  await expect(page.getByRole("heading", { level: 1, name: "КП на одобрение" })).toBeVisible();
}

async function openApprovals(page: Page, query = ""): Promise<void> {
  await spaGoto(page, `/eds/approvals${query}`);
  await expect(page.getByRole("heading", { level: 1, name: "На согласовании" })).toBeVisible();
}

function row(page: Page, label: string) {
  return page.getByRole("row").filter({
    has: page.getByRole("link", { name: new RegExp(`^Показать .* ${label} в боковом окне`) }),
  });
}

const quoteForm = (page: Page) => page.locator(PANEL).getByRole("form", { name: "Одобрение КП" });
const memoForm = (page: Page) =>
  page.locator(PANEL).getByRole("form", { name: "Согласование документа" });

test.describe("КП на одобрение: директор", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; телефон — блок @mobile");

  test("список → КП в боковом окне → карточка → «Одобрить КП» с каналами → КП ушло из «Моего шага»", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openDrafts(page);

    // список: КП · заявка · клиент · сумма · срок · поступило · статус · «Открыть»; решённое КП-113 в «Моём шаге» нет
    const first = row(page, "КП-2026/115");
    await expect(first.getByText("ООО «Демо-Рейл»")).toBeVisible();
    await expect(first.getByText("ЗВ-2026-104")).toBeVisible();
    await expect(first.getByText("На одобрении")).toBeVisible();
    await expect(page.getByRole("row")).toHaveCount(1 + 4);
    await settledScreenshot(page, "list");
    await expectNoViolations(page, "список КП");

    // клик по строке — КП в боковом окне без перехода
    await first.getByText("ООО «Демо-Рейл»").click();
    const panel = page.locator(PANEL);
    await expect(panel.getByRole("heading", { level: 3, name: "КП-2026/115" })).toBeVisible();
    await expect(quoteForm(page)).toBeVisible();
    await expect(page).toHaveURL(/\/eds\/drafts\?/);

    // карточка КП
    // окно поверх списка закрывает правые столбцы (ORCHESTRATOR §3 п. 18): сначала скрыть его
    await page.getByRole("button", { name: "Скрыть боковое окно" }).click();
    await first.getByRole("link", { name: "Открыть карточку КП КП-2026/115" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "КП-2026/115" })).toBeVisible();
    await expect(page.getByText("Черновик · отправка заблокирована")).toBeVisible();
    const steps = page.getByRole("list", { name: "Путь заявки ЗВ-2026-104" });
    await expect(steps.getByRole("listitem")).toHaveCount(7);
    await expect(steps.locator('[aria-current="step"]')).toContainText("КП");
    const lines = page.getByRole("table", { name: "Состав КП" });
    await expect(lines.getByRole("row")).toHaveCount(1 + 2);
    await expect(lines.getByText("Привод стрелочный СП-6")).toBeVisible();
    await expect(page.getByText("Итого с НДС")).toBeVisible();
    // внутренний блок — только роли с `cost_margin`
    const internal = page.getByRole("region", { name: "Внутренние данные" });
    await expect(internal.getByText("Себестоимость")).toBeVisible();
    await expect(internal.getByText("17.6 %")).toBeVisible();
    await expect(internal.getByText("Клиент получит PDF без этих полей.")).toBeVisible();
    await expect(page.getByRole("link", { name: "ВХ-104/26" })).toBeVisible();

    // «Одобрение»: чек-лист с датой и автором, каналы, «Что произойдёт»
    const form = quoteForm(page);
    const checklist = form.getByRole("list", { name: "Чек-лист одобрения" });
    await expect(checklist.getByRole("listitem")).toHaveCount(4);
    await expect(checklist.getByText("Демо Снабженцев")).toBeVisible();
    await expect(form.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await expect(form.getByRole("checkbox", { name: "Telegram-бот" })).toBeChecked();
    await expect(form.getByRole("checkbox", { name: "Почта" })).toBeChecked();
    await expect(form.getByRole("button", { name: APPROVE })).toBeEnabled();
    await expect(form.getByRole("button", { name: "Вернуть на доработку" })).toBeDisabled();
    await settledScreenshot(page, "card-approval");
    await expectNoViolations(page, "карточка КП с «Одобрением»");

    // канал «Почта» снят — в «Что произойдёт» его нет
    await form.getByRole("checkbox", { name: "Почта" }).uncheck();
    await expect(form.getByRole("group", { name: "Что произойдёт" })).toContainText(
      "Telegram-бот, Кабинет",
    );
    await form.getByRole("button", { name: APPROVE }).click();

    await expect(page.getByText(/КП КП-2026\/115 одобрено: ИСХ-/)).toBeVisible();
    await expect(page.locator(PANEL).getByRole("heading", { name: "КП одобрено" })).toBeVisible();
    await expect(page.getByText("ИСХ-042/26").first()).toBeVisible();
    await settledScreenshot(page, "approved");

    // КП ушло из «Моего шага», но есть в «Все КП» со статусом «Одобрено»
    await openDrafts(page);
    await expect(page.getByRole("row")).toHaveCount(1 + 3);
    await page.getByRole("radiogroup", { name: "Какие КП показать" }).getByText("Все КП").click();
    await expect(row(page, "КП-2026/115").getByText("Одобрено")).toBeVisible();
  });

  test("КП с незелёным чек-листом: «Одобрить» неактивна и подписана, какой пункт не зелёный; «Вернуть на доработку» с комментарием", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/116")}`);
    await expect(page.getByRole("heading", { level: 1, name: "КП-2026/116" })).toBeVisible();

    const form = quoteForm(page);
    const approve = form.getByRole("button", { name: APPROVE });
    await expect(approve).toBeDisabled();
    await expect(
      form.getByText("Одобрить нельзя: нет визы гл. инженера, маржа ниже порога резолюции."),
    ).toBeVisible();
    await expect(approve).toHaveAccessibleDescription(/нет визы гл\. инженера/);
    // канал «Кабинет» недоступен у этой компании
    await expect(form.getByRole("checkbox", { name: "Кабинет" })).toBeDisabled();
    await expect(form.getByText("Недоступен: у компании клиента нет кабинета.")).toBeVisible();
    await settledScreenshot(page, "blocked");
    await expectNoViolations(page, "неактивная кнопка с подписью");

    // возврат: комментарий обязателен
    const back = form.getByRole("button", { name: "Вернуть на доработку" });
    await expect(back).toBeDisabled();
    await expect(form.getByText("Кнопка неактивна, пока нет комментария.")).toBeVisible();
    await form.getByLabel("Комментарий").fill("Нужна виза гл. инженера и пересчёт маржи.");
    await expect(back).toBeEnabled();
    await back.click();

    await expect(page.getByText("КП КП-2026/116 возвращено на доработку")).toBeVisible();
    await expect(page.getByText("Нужна виза гл. инженера и пересчёт маржи.").first()).toBeVisible();
    await expect(
      page.locator(PANEL).getByRole("heading", { name: "КП возвращено на доработку" }),
    ).toBeVisible();
  });

  test("срок клиента просрочен — предупреждение, не блок: КП одобряется с отметкой; почта недоступна без e-mail", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/117")}`);
    await expect(page.getByRole("heading", { level: 1, name: "КП-2026/117" })).toBeVisible();

    const form = quoteForm(page);
    await expect(form.getByText(/просрочен, это предупреждение/)).toBeVisible();
    await expect(form.getByText(/Одобрить можно: в журнале появится отметка/)).toBeVisible();
    await expect(form.getByRole("checkbox", { name: "Почта" })).toBeDisabled();
    await expect(form.getByText("Недоступна: у контакта не указан e-mail.")).toBeVisible();
    const approve = form.getByRole("button", { name: APPROVE });
    await expect(approve).toBeEnabled();
    await settledScreenshot(page, "late");
    await approve.click();

    await expect(page.getByText("Одобрено с опозданием")).toBeVisible();
  });

  test("КП уже решено другим директором — понятное сообщение, карточка обновляется", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/115")}`);
    const form = quoteForm(page);
    await expect(form).toBeVisible();
    // другой директор вернул КП, пока форма открыта
    await page.evaluate(`fetch("/api/v1/eds/quotes/40000000-0000-4000-8000-000000000115/decision", {
      method: "POST", headers: { "content-type": "application/json", "x-csrf-token": "x" },
      body: JSON.stringify({ decision: "return", comment: "дубль" })
    })`);
    await form.getByRole("button", { name: APPROVE }).click();

    await expect(
      page
        .getByText(/Не сохранено: КП уже решено другим директором или заменено новой версией/)
        .first(),
    ).toBeVisible();
    await expect(
      page.locator(PANEL).getByRole("heading", { name: "КП возвращено на доработку" }),
    ).toBeVisible();
  });
});

test.describe("КП на одобрение: данные ERP", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе");

  test("ERP не ответил: «Одобрить» неактивна с подписью, виден итог снимка; «Вернуть» доступно", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/118")}`);
    await expect(page.getByRole("heading", { level: 1, name: "КП-2026/118" })).toBeVisible();

    await expect(page.getByText("ERP не отвечает, данные неполные")).toBeVisible();
    await expect(page.getByText(/Состав КП не получен из ERP/)).toBeVisible();
    await expect(page.getByText("Итог по снимку КП")).toBeVisible();
    const form = quoteForm(page);
    const approve = form.getByRole("button", { name: APPROVE });
    await expect(approve).toBeDisabled();
    await expect(form.getByText("Нет данных КП из ERP — обновите карточку.")).toBeVisible();
    await expect(approve).toHaveAccessibleDescription(/Нет данных КП из ERP/);
    await settledScreenshot(page, "erp-down");
    await expectNoViolations(page, "ERP не ответил: карточка КП");
  });
});

test.describe("КП на одобрение: менеджер", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе");

  test("видит КП без себестоимости и маржи и без кнопок решения", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await openDrafts(page);

    // менеджер открывает «Все КП» сам: у него нет «моего шага»
    await expect(page.getByRole("radiogroup", { name: "Какие КП показать" })).toHaveCount(0);
    await expect(page.getByRole("row")).toHaveCount(1 + 5);
    await settledScreenshot(page, "manager-list");

    await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/115")}`);
    await expect(page.getByRole("heading", { level: 1, name: "КП-2026/115" })).toBeVisible();
    await expect(page.getByText("Только просмотр")).toBeVisible();
    await expect(page.getByText(/Состав КП не получен из ERP/)).toBeVisible();
    await expect(page.getByText("Внутренние данные")).toHaveCount(0);
    await expect(page.getByText("Себестоимость")).toHaveCount(0);
    await expect(page.getByText("17.6")).toHaveCount(0);
    await expect(page.getByRole("button", { name: APPROVE })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Вернуть на доработку" })).toHaveCount(0);
    await expect(page.getByRole("form", { name: "Одобрение КП" })).toHaveCount(0);
    await expect(
      page.locator(PANEL).getByRole("heading", { name: "КП ждёт решения директора" }),
    ).toBeVisible();
    await settledScreenshot(page, "manager-card");
    await expectNoViolations(page, "менеджер: карточка КП");
  });

  test("роль без раздела «КП на одобрение» получает экран «Нет доступа»", async ({ page }) => {
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/eds/drafts");

    await expect(page.getByRole("heading", { name: "Нет доступа" })).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);
  });
});

test.describe("На согласовании: служебные записки", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; телефон — блок @mobile");

  test("служебка с суммой: список → карточка → «Согласовать» → документ идёт бухгалтеру", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openApprovals(page);

    const first = row(page, "СЗ-2026/014");
    await expect(first.getByText("Оплата аренды склада за ноябрь")).toBeVisible();
    await expect(first.getByText("Демо Менеджеров")).toBeVisible();
    await expect(first.getByText("На согласовании · Директор")).toBeVisible();
    // шаг бухгалтера (СЗ-2026/015) директору не принадлежит: «Счета и оплаты» он только читает (D2-4)
    await expect(page.getByRole("row")).toHaveCount(1 + 4);
    await expect(row(page, "СЗ-2026/015")).toHaveCount(0);
    await settledScreenshot(page, "memos-list");
    await expectNoViolations(page, "список согласований");

    await first.getByRole("link", { name: "Открыть карточку документа СЗ-2026/014" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "СЗ-2026/014" })).toBeVisible();
    await expect(page.getByText("Прошу согласовать оплату аренды склада")).toBeVisible();
    await expect(page.getByRole("link", { name: "Скачать файл счёт-аренда.pdf" })).toBeVisible();
    const route = page.getByRole("list", { name: "Маршрут согласования" });
    await expect(route.getByRole("listitem")).toHaveCount(3);
    await expect(route).toContainText("Автор: Демо Менеджеров");
    await expect(route).toContainText("Бухгалтер");

    const form = memoForm(page);
    await expect(form.getByRole("group", { name: "Что произойдёт" })).toContainText(
      "Дальше документ получит: Бухгалтер.",
    );
    const back = form.getByRole("button", { name: "Вернуть на доработку" });
    const reject = form.getByRole("button", { name: "Отклонить" });
    await expect(back).toBeDisabled();
    await expect(reject).toBeDisabled();
    await expect(form.getByText(/кнопки неактивны, пока он пуст/)).toBeVisible();
    await settledScreenshot(page, "memo-card-agree");
    await expectNoViolations(page, "карточка документа с «Согласованием»");

    await form.getByRole("button", { name: "Согласовать" }).click();
    await expect(page.getByText("Документ согласован", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Передана бухгалтеру").first()).toBeVisible();
    await settledScreenshot(page, "memo-agreed");

    // шаг теперь у бухгалтера: на шаге директора документа уже нет, в «Все мои согласования» он со словом «Бухгалтер»
    await openApprovals(page);
    await expect(row(page, "СЗ-2026/014")).toHaveCount(0);
    await page
      .getByRole("radiogroup", { name: "Какие документы показать" })
      .getByText("Все мои согласования")
      .click();
    await expect(row(page, "СЗ-2026/014").getByText("На согласовании · Бухгалтер")).toBeVisible();
  });

  test("«Отклонить» и «Вернуть на доработку»: комментарий обязателен", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, `/eds/approvals/${encodeURIComponent("ОТ-2026/009")}`);
    await expect(page.getByRole("heading", { level: 1, name: "ОТ-2026/009" })).toBeVisible();
    const form = memoForm(page);
    const reject = form.getByRole("button", { name: "Отклонить" });
    await expect(reject).toBeDisabled();
    await form.getByLabel("Комментарий").fill("Нужны данные по неликвиду.");
    await expect(reject).toBeEnabled();
    await reject.click();
    await expect(page.getByText("Документ отклонён", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Нужны данные по неликвиду.").first()).toBeVisible();

    await spaGoto(page, `/eds/approvals/${encodeURIComponent("ЗЯ-2026/003")}`);
    const form2 = memoForm(page);
    await expect(form2.getByRole("button", { name: "Вернуть на доработку" })).toBeDisabled();
    await form2.getByLabel("Комментарий").fill("Укажите замещающего.");
    await form2.getByRole("button", { name: "Вернуть на доработку" }).click();
    await expect(
      page.getByText("Документ возвращён на доработку", { exact: true }).first(),
    ).toBeVisible();
  });

  test("автор без права решения видит свой документ в режиме чтения", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await openApprovals(page);
    await expect(page.getByRole("radiogroup", { name: "Какие документы показать" })).toHaveCount(0);
    await expect(page.getByRole("row")).toHaveCount(1 + 1);

    await page.getByRole("link", { name: "Открыть карточку документа СЗ-2026/014" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "СЗ-2026/014" })).toBeVisible();
    await expect(page.getByText("Только просмотр")).toBeVisible();
    await expect(page.getByRole("button", { name: "Согласовать" })).toHaveCount(0);
    await expect(page.getByRole("form", { name: "Согласование документа" })).toHaveCount(0);
    await expect(
      page.locator(PANEL).getByRole("heading", { name: "Документ на согласовании" }),
    ).toBeVisible();
    await expectNoViolations(page, "автор: карточка документа");
  });
});

test.describe("На согласовании: бухгалтер", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе");

  test("служебка на шаге бухгалтера: «Принять к оплате» и «Вернуть»; чужие шаги не показываются", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    await openApprovals(page);

    // на шаге бухгалтера одна служебка; документ на шаге директора ему не показывается
    await expect(page.getByRole("row")).toHaveCount(1 + 1);
    const first = row(page, "СЗ-2026/015");
    await expect(first.getByText("На согласовании · Бухгалтер")).toBeVisible();
    await first.getByRole("link", { name: "Открыть карточку документа СЗ-2026/015" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "СЗ-2026/015" })).toBeVisible();

    const form = memoForm(page);
    await expect(form.getByRole("button", { name: "Принять к оплате" })).toBeEnabled();
    await expect(form.getByRole("button", { name: "Вернуть", exact: true })).toBeDisabled();
    await expect(form.getByRole("button", { name: "Согласовать" })).toHaveCount(0);
    await expect(form.getByRole("group", { name: "Что произойдёт" })).toContainText(
      "появится в «Счета и оплаты»",
    );
    await settledScreenshot(page, "accountant-agree");
    await expectNoViolations(page, "бухгалтер: «Согласование»");

    await form.getByRole("button", { name: "Принять к оплате" }).click();
    await expect(page.getByText("Документ принят к оплате", { exact: true }).first()).toBeVisible();
  });
});

test.describe("Одобрение и согласование на телефоне @mobile", () => {
  test("@mobile КП: список карточками; «Одобрение» — лист на весь экран с кнопками внизу", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/drafts");
    await expect(page.getByRole("list", { name: "КП на одобрение" })).toBeVisible();
    await settledScreenshot(page, "mobile-list");
    await expectNoViolations(page, "телефон: список КП");

    await page.getByRole("link", { name: "Показать КП КП-2026/115 в боковом окне" }).click();
    const sheet = page.getByRole("dialog", { name: /^Одобрение/ });
    await expect(sheet.getByRole("form", { name: "Одобрение КП" })).toBeVisible();

    const viewport = page.viewportSize();
    const box = await sheet.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual((viewport?.width ?? 0) - 1);
    expect(box?.height).toBeGreaterThanOrEqual((viewport?.height ?? 0) - 1);
    for (const name of [APPROVE, "Вернуть на доработку"]) {
      await expect(sheet.getByRole("button", { name })).toBeInViewport();
    }
    const submit = await sheet.getByRole("button", { name: APPROVE }).boundingBox();
    expect(submit?.y ?? 0).toBeGreaterThan((viewport?.height ?? 0) / 2);
    await settledScreenshot(page, "mobile-sheet");
    await expectNoViolations(page, "телефон: лист «Одобрение»");

    await sheet.getByRole("button", { name: APPROVE }).click();
    await expect(page.getByText(/КП КП-2026\/115 одобрено/)).toBeVisible();
    await expect(page.getByRole("dialog", { name: /^Одобрение/ })).toHaveCount(0);
  });

  test("@mobile КП: карточка, неактивная кнопка на листе с подписью", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, `/eds/drafts/${encodeURIComponent("КП-2026/116")}`);
    await expect(page.getByRole("heading", { level: 1, name: "КП-2026/116" })).toBeVisible();
    await settledScreenshot(page, "mobile-card");
    await expectNoViolations(page, "телефон: карточка КП");

    await page.getByRole("button", { name: "Одобрить КП", exact: true }).click();
    const sheet = page.getByRole("dialog", { name: /^Одобрение/ });
    await expect(sheet.getByRole("button", { name: APPROVE })).toBeDisabled();
    await expect(sheet.getByText(/Одобрить нельзя: нет визы гл\. инженера/)).toBeVisible();
    await settledScreenshot(page, "mobile-blocked");
  });

  test("@mobile служебка: «Согласование» — лист с кнопками внизу", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/approvals");
    await expect(page.getByRole("list", { name: "Документы на согласовании" })).toBeVisible();
    await settledScreenshot(page, "mobile-memos");

    await page.getByRole("link", { name: "Показать документ СЗ-2026/014 в боковом окне" }).click();
    const sheet = page.getByRole("dialog", { name: /^Согласование/ });
    await expect(sheet.getByRole("form", { name: "Согласование документа" })).toBeVisible();
    for (const name of ["Согласовать", "Вернуть на доработку", "Отклонить"]) {
      await expect(sheet.getByRole("button", { name })).toBeInViewport();
    }
    await settledScreenshot(page, "mobile-agree");
    await expectNoViolations(page, "телефон: лист «Согласование»");

    await sheet.getByRole("button", { name: "Согласовать" }).click();
    await expect(page.getByText("Документ согласован", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("dialog", { name: /^Согласование/ })).toHaveCount(0);
  });
});
