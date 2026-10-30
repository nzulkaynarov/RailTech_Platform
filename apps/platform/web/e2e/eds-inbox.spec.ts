import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// EDS · Входящие письма и «Резолюция» директора на MSW (D1-3): сценарий директора целиком — Входящие → письмо → резолюция →
// «Утвердить»; отдельно «Вернуть менеджеру» и «Отклонить»; ошибка резолюции со словами и сохранённым текстом; роли только для
// чтения не видят кнопок решения; axe (WCAG 2.1 AA); на 390 px «Резолюция» — лист на весь экран с кнопками внизу (@mobile).
const PANEL = "#pf-context-panel";
const SUBMIT = "Утвердить резолюцию → задание в расчёт";

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

async function openInbox(page: Page, query = ""): Promise<void> {
  await spaGoto(page, `/eds/inbox${query}`);
  await expect(page.getByRole("heading", { level: 1, name: "Входящие письма" })).toBeVisible();
}

function row(page: Page, number: string) {
  return page
    .getByRole("row")
    .filter({ has: page.getByRole("link", { name: `Показать письмо ${number} в боковом окне` }) });
}

test.describe("Входящие письма: директор", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; телефон — блок @mobile");

  test("Входящие → письмо в боковом окне → резолюция → «Утвердить» → задание ушло", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await openInbox(page);

    // список: ВХ-номер · тема · клиент · заявка · получено · статус словом · «Открыть»
    const first = row(page, "ВХ-104/26");
    await expect(
      first.getByText("Запрос коммерческого предложения на стрелочные приводы"),
    ).toBeVisible();
    await expect(first.getByText("ООО «Демо-Рейл»")).toBeVisible();
    await expect(first.getByText("ЗВ-2026-104")).toBeVisible();
    await expect(first.getByText("Ждёт резолюции")).toBeVisible();
    await expect(page.getByRole("row")).toHaveCount(1 + 4);
    await settledScreenshot(page, "list");
    await expectNoViolations(page, "список");

    // клик по строке — письмо в боковом окне без перехода
    await first.getByText("ООО «Демо-Рейл»").click();
    const panel = page.locator(PANEL);
    await expect(panel.getByRole("heading", { level: 3, name: "ВХ-104/26" })).toBeVisible();
    await expect(panel.getByRole("form", { name: "Резолюция директора" })).toBeVisible();
    await expect(page).toHaveURL(/\/eds\/inbox\?/);
    await settledScreenshot(page, "list-panel");

    // карточка письма
    // окно поверх списка закрывает правые столбцы (ORCHESTRATOR §3 п. 18): сначала скрыть его
    await page.getByRole("button", { name: "Скрыть боковое окно" }).click();
    await first.getByRole("link", { name: "Открыть карточку письма ВХ-104/26" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-104/26" })).toBeVisible();
    const steps = page.getByRole("list", { name: "Путь заявки ЗВ-2026-104" });
    await expect(steps.getByRole("listitem")).toHaveCount(7);
    await expect(steps.locator('[aria-current="step"]')).toContainText("Резолюция");
    await expect(
      page.getByText("Просим рассмотреть поставку 12 стрелочных приводов"),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Скачать файл запрос-на-кп.pdf" })).toBeVisible();
    await expect(page.getByRole("link", { name: "ЗВ-2026-104" })).toBeVisible();

    const form = panel.getByRole("form", { name: "Резолюция директора" });
    await expect(form.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
    await expect(form.getByRole("checkbox", { name: /Бухгалтер/ })).not.toBeChecked();
    await expect(form.getByRole("button", { name: "Вернуть менеджеру" })).toBeDisabled();
    await expect(form.getByText(/Кнопки неактивны, пока нет комментария/)).toBeVisible();
    await settledScreenshot(page, "card-panel");
    await expectNoViolations(page, "карточка с панелью «Резолюция»");

    // пустая форма — подсказки у полей
    await form.getByRole("button", { name: SUBMIT }).click();
    await expect(form.getByText("Напишите текст резолюции.")).toBeVisible();
    await expect(form.getByText("Выберите сотрудника.")).toBeVisible();

    // срок в прошлом отвергает EDS — текст остаётся в черновике
    await form.getByLabel("Текст резолюции").fill("Посчитать с запасом по складу, сроки уточнить.");
    await form
      .getByLabel("Сотрудник: Снабженец")
      .selectOption({ label: "Демо Снабженцев · Специалист по снабжению" });
    await form.getByLabel("Срок расчёта").fill("2020-01-01");
    await form.getByRole("button", { name: SUBMIT }).click();
    await expect(form.getByText("Срок расчёта не может быть в прошлом.")).toBeVisible();

    // срок «сегодня плюс два дня» принимает и форма, и EDS
    const soon = new Date(Date.now() + 2 * 86_400_000).toISOString().slice(0, 10);
    await form.getByLabel("Срок расчёта").fill(soon);
    await form.getByLabel("Маржа не ниже, %").fill("15");
    await form.getByRole("button", { name: SUBMIT }).click();

    await expect(page.getByText("Резолюция наложена: задание ушло исполнителям")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Решение директора" })).toBeVisible();
    await expect(page.getByText("15 %")).toBeVisible();
    await expect(panel.getByRole("heading", { name: "Решение по письму принято" })).toBeVisible();
    await expect(steps.locator('[aria-current="step"]')).toContainText("Расчёт");
    await settledScreenshot(page, "resolved");

    // письма больше нет в «Ждёт резолюции», зато есть в «Резолюция наложена»
    await openInbox(page);
    await expect(page.getByRole("row")).toHaveCount(1 + 3);
    await page
      .getByRole("radiogroup", { name: "Статус письма" })
      .getByText("Резолюция наложена")
      .click();
    await expect(row(page, "ВХ-104/26").getByText("Резолюция наложена")).toBeVisible();
  });

  test("ошибка резолюции словами; введённое в форме не теряется", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-105%2F26");
    const form = page.locator(PANEL).getByRole("form", { name: "Резолюция директора" });

    await form.getByLabel("Текст резолюции").fill("Расчёт нужен срочно.");
    await form.getByLabel("Сотрудник: Снабженец").selectOption("31");
    // Другой директор уже решил письмо: EDS отвечает «не ждёт резолюции»
    await page.evaluate(`fetch("/api/v1/eds/letters/20000000-0000-4000-8000-000000000105/reject", {
      method: "POST", headers: { "content-type": "application/json", "x-csrf-token": "x" }, body: JSON.stringify({ reason: "дубль" })
    })`);
    await form.getByRole("button", { name: SUBMIT }).click();

    await expect(
      form.getByText("Резолюция не сохранена: письмо уже не ждёт резолюции, обновите карточку."),
    ).toBeVisible();
    await expect(form.getByLabel("Текст резолюции")).toHaveValue("Расчёт нужен срочно.");
    await settledScreenshot(page, "error");
    await expectNoViolations(page, "ошибка резолюции");
  });

  test("«Вернуть менеджеру»: комментарий обязателен, письмо получает статус «Возвращено»", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-106%2F26");
    const form = page.locator(PANEL).getByRole("form", { name: "Резолюция директора" });
    const back = form.getByRole("button", { name: "Вернуть менеджеру" });

    await expect(back).toBeDisabled();
    await form.getByLabel("Комментарий").fill("Нет объёма и сроков, уточните у клиента.");
    await expect(back).toBeEnabled();
    await back.click();

    await expect(page.getByText("Письмо возвращено менеджеру", { exact: true })).toBeVisible();
    await expect(page.getByText("Нет объёма и сроков, уточните у клиента.").first()).toBeVisible();
    await expect(page.getByText("Возвращено", { exact: true }).first()).toBeVisible();
  });

  test("«Отклонить»: причина обязательна, на шкале — «Отказ»", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-105%2F26");
    const form = page.locator(PANEL).getByRole("form", { name: "Резолюция директора" });
    const reject = form.getByRole("button", { name: "Отклонить" });

    await expect(reject).toBeDisabled();
    await form.getByLabel("Комментарий").fill("Не наш профиль.");
    await reject.click();

    await expect(page.getByText("Письмо отклонено", { exact: true })).toBeVisible();
    await expect(page.getByText("Не наш профиль.").first()).toBeVisible();
    await expect(page.getByText("Отказ").first()).toBeVisible();
  });

  test("ERP не ответил — карточка частичная, с плашкой; номер ВХ-104/26 без кодирования открывает письмо", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox/ВХ-107/26");

    await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-107/26" })).toBeVisible();
    await expect(page.getByText("ERP не отвечает, данные неполные")).toBeVisible();
    await expect(page.getByRole("list", { name: /Путь заявки/ })).toBeVisible();
    await expectNoViolations(page, "частичная карточка");

    await spaGoto(page, "/eds/inbox/ВХ-104/26");
    await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-104/26" })).toBeVisible();
  });
});

test.describe("Входящие письма: роли только для чтения", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе");

  for (const email of ["manager@demo.example", "accountant@demo.example"]) {
    test(`${email}: карточка без кнопок решения`, async ({ page }) => {
      await loginAndWait(page, email);
      await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-104%2F26");

      await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-104/26" })).toBeVisible();
      await expect(page.getByText("Только просмотр")).toBeVisible();
      const panel = page.locator(PANEL);
      await expect(
        panel.getByRole("heading", { name: "Письмо ждёт резолюции директора" }),
      ).toBeVisible();
      await expect(page.getByRole("button", { name: SUBMIT })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Отклонить" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Вернуть менеджеру" })).toHaveCount(0);
      await expect(page.getByRole("form", { name: "Резолюция директора" })).toHaveCount(0);
      await expectNoViolations(page, `${email}: карточка`);
    });
  }

  test("роль без раздела «Входящие» получает экран «Нет доступа»", async ({ page }) => {
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/eds/inbox");

    await expect(page.getByRole("heading", { name: "Нет доступа" })).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);
  });
});

test.describe("Входящие письма на телефоне @mobile", () => {
  test("@mobile список карточками; «Резолюция» — лист на весь экран с кнопками внизу", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox");
    await expect(page.getByRole("list", { name: "Входящие письма" })).toBeVisible();
    await settledScreenshot(page, "mobile-list");
    await expectNoViolations(page, "телефон: список");

    await page.getByRole("link", { name: "Показать письмо ВХ-104/26 в боковом окне" }).click();
    const sheet = page.getByRole("dialog", { name: /^Резолюция/ });
    await expect(sheet.getByRole("form", { name: "Резолюция директора" })).toBeVisible();

    const viewport = page.viewportSize();
    const box = await sheet.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual((viewport?.width ?? 0) - 1);
    expect(box?.height).toBeGreaterThanOrEqual((viewport?.height ?? 0) - 1);
    // главная кнопка и «Вернуть / Отклонить» закреплены внизу листа и видны без прокрутки
    for (const name of [SUBMIT, "Вернуть менеджеру", "Отклонить"]) {
      const button = sheet.getByRole("button", { name });
      await expect(button).toBeInViewport();
    }
    const submit = await sheet.getByRole("button", { name: SUBMIT }).boundingBox();
    expect(submit?.y ?? 0).toBeGreaterThan((viewport?.height ?? 0) / 2);
    await settledScreenshot(page, "mobile-sheet");
    await expectNoViolations(page, "телефон: лист «Резолюция»");

    // решение с телефона
    await sheet.getByLabel("Текст резолюции").fill("Посчитать в первую очередь.");
    await sheet.getByLabel("Сотрудник: Снабженец").selectOption("31");
    await sheet.getByRole("button", { name: SUBMIT }).click();
    await expect(page.getByText("Резолюция наложена: задание ушло исполнителям")).toBeVisible();
    await expect(page.getByRole("dialog", { name: /^Резолюция/ })).toHaveCount(0);
  });

  test("@mobile карточка письма: «Наложить резолюцию» открывает лист; ошибка со словами", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox/%D0%92%D0%A5-105%2F26");
    await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-105/26" })).toBeVisible();
    await settledScreenshot(page, "mobile-card");
    await expectNoViolations(page, "телефон: карточка");

    await page.getByRole("button", { name: "Наложить резолюцию" }).click();
    const sheet = page.getByRole("dialog", { name: /^Резолюция/ });
    await sheet.getByLabel("Текст резолюции").fill("Нужен расчёт.");
    await sheet.getByLabel("Сотрудник: Снабженец").selectOption("31");
    await sheet.getByLabel("Срок расчёта").fill("2020-01-01");
    await sheet.getByRole("button", { name: SUBMIT }).click();
    await expect(sheet.getByText("Срок расчёта не может быть в прошлом.")).toBeVisible();
    await settledScreenshot(page, "mobile-error");
  });
});
