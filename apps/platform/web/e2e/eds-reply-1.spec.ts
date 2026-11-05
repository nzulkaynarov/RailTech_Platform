import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, openAvatarMenu, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption, fillDate, pickFiles } from "./support/fields";

// EDS-REPLY-1 «Ответ на входящее» на MSW: требование ГНК → поручение «Подготовить ответ» исполнителю без права регистрировать →
// «Подготовить ответ» (форма заполнена из входящего) → «Передать на регистрацию» → у делопроизводителя задача «Зарегистрировать
// ИСХ» и уведомление → «Зарегистрировать и отправить» → поручение исполнено, ВХ «Исполнено», исполнителю уведомление, связь
// видна с обеих сторон. Второй сценарий: письмо не ушло — метка «Не отправлено», уведомления, «Отправить ещё раз».
// Снимки 1440 и 390 с axe — E2E_SCREENSHOT_DIR (docs/screens/EDS-REPLY-1).
const WIDE = 1440;
const NARROW = 390;
const NUMBER = "ВХ-109/26";

function companyDay(offset: number): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tashkent",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(Date.now() + offset * 86_400_000));
}

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

async function at(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
}

/** Текущий экран на обеих ширинах: снимок (если задан каталог) и axe 0; после — снова широкий экран. */
async function both(page: Page, name: string, ready?: (page: Page) => Promise<void>) {
  for (const width of [WIDE, NARROW]) {
    await at(page, width);
    await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 10_000 });
    if (ready) await ready(page);
    await waitForMotionEnd(page);
    const dir = process.env["E2E_SCREENSHOT_DIR"];
    if (dir) {
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
    }
    await expectNoViolations(page, `${name} ${String(width)}`);
  }
  await at(page, WIDE);
}

async function switchTo(page: Page, email: string): Promise<void> {
  await at(page, WIDE);
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль").fill("demo-pass-1");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/dashboard\/queue$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

function queueRow(page: Page, text: string): Locator {
  return page
    .getByRole("region", { name: "Что сделать сейчас" })
    .getByRole("listitem")
    .filter({ hasText: text });
}

function side(page: Page): Locator {
  return page.locator("#pf-context-panel");
}

/** Делопроизводитель регистрирует требование ГНК с проектом «Подготовить ответ» исполнителю, директор утверждает проект. */
async function incomingWithReplyInstruction(page: Page): Promise<void> {
  await at(page, WIDE);
  await loginAndWait(page, "registrar@demo.example");
  await spaGoto(page, "/eds/register");
  await chooseOption(page.getByLabel("Вид документа"), "Требование или уведомление ГНК");
  await page.getByLabel("Корреспондент", { exact: true }).fill("ГНИ Мирабадского района");
  await page.getByLabel("ИНН корреспондента").fill("305123456");
  await page.getByLabel("Исходящий номер отправителя").fill("14-02/3381");
  await page.getByLabel("Тема").fill("Требование о представлении пояснений по НДС");
  await pickFiles(page.getByLabel("Файл документа"), {
    name: "trebovanie.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 demo"),
  });
  await expect(page.getByText("загружен")).toBeVisible();
  await chooseOption(page.getByLabel("Тип резолюции"), "Подготовить ответ");
  await chooseOption(page.getByLabel("Ответственный"), "Демо Широков · Менеджер-универсал");
  await fillDate(page.getByLabel("Срок исполнения"), companyDay(3));
  await page.getByRole("button", { name: "Зарегистрировать", exact: true }).click();
  await expect(page.getByText(new RegExp(`Зарегистрировано: ${NUMBER}`))).toBeVisible();

  await switchTo(page, "director@demo.example");
  await spaGoto(page, `/eds/inbox/${encodeURIComponent(NUMBER)}?panel=open&tab=resolution`);
  await page.getByRole("button", { name: "Утвердить проект" }).click();
  await expect(page.getByText("Резолюция наложена: поручение ушло исполнителям")).toBeVisible();
}

/** Исполнитель: «Подготовить ответ» → форма заполнена из входящего → текст → «Передать на регистрацию». */
async function executorHandsOver(page: Page, email: string, screens: boolean): Promise<void> {
  await switchTo(page, "universal@demo.example");
  await queueRow(page, `Подготовить ответ на письмо ${NUMBER}`)
    .getByRole("link", { name: /^Открыть:/ })
    .click();
  await page.getByRole("link", { name: "Подготовить ответ" }).click();
  await expect(page).toHaveURL(/\/eds\/new\?type=letter&reply_to=.*&reply_id=[0-9a-f-]{36}/);

  // Поля заполнены из входящего (корреспондент, ИНН, тема); почты в письме нет — пусто, вводит исполнитель.
  await expect(page.getByLabel("Адресат (организация)")).toHaveValue("ГНИ Мирабадского района");
  await expect(page.getByLabel("ИНН адресата")).toHaveValue("305123456");
  await expect(page.getByLabel("Тема")).toHaveValue(
    /^На ВХ-109\/26 от \d{2}\.\d{2}\.\d{4}: Требование о представлении пояснений по НДС$/,
  );
  await expect(page.getByLabel("В ответ на входящее")).toHaveValue(NUMBER);
  await expect(page.getByLabel("Почта адресата")).toHaveValue("");
  await expect(
    page.getByText(/Заполнено из ВХ-109\/26: проверьте корреспондента, почту и тему/),
  ).toBeVisible();
  if (screens) await both(page, "reply-form-prefilled");

  await page.getByLabel("Почта адресата").fill(email);
  await page
    .getByLabel("Текст", { exact: true })
    .fill(
      "На требование № 14-02/3381 сообщаем: расхождения вызваны поступлением счетов-фактур после отчётной даты.",
    );
  await page.getByRole("button", { name: "Передать на регистрацию" }).click();
  await expect(page.getByText("Передано на регистрацию делопроизводителю.")).toBeVisible();

  // На рабочем экране поручения: ответ передан, второго «Подготовить ответ» нет.
  await spaGoto(page, `/eds/tasks/${encodeURIComponent(NUMBER)}`);
  const block = page.getByRole("heading", { level: 2, name: "Ответ на письмо" });
  await expect(block).toBeVisible();
  await expect(page.getByText("Черновик передан на регистрацию делопроизводителю.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Подготовить ответ" })).toHaveCount(0);
  if (screens) await both(page, "task-reply-handed");
}

test.describe("EDS-REPLY-1: ответ на входящее", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("поручение → «Подготовить ответ» → «Передать на регистрацию» → задача делопроизводителю → ИСХ → поручение исполнено", async ({
    page,
  }) => {
    test.setTimeout(240_000);
    await incomingWithReplyInstruction(page);
    await executorHandsOver(page, "gni-mirabad@example.uz", true);

    // Делопроизводитель: уведомление и строка «Зарегистрировать ИСХ» в «Моих задачах».
    await switchTo(page, "registrar@demo.example");
    const row = queueRow(page, `Зарегистрировать ИСХ: ответ на ${NUMBER}`);
    await expect(row).toBeVisible();
    await both(page, "queue-register-reply");
    await spaGoto(page, "/dashboard/queue?panel=open&tab=notifications");
    await expect(page.getByText(`Зарегистрируйте ответ на ${NUMBER}`).first()).toBeVisible();
    await spaGoto(page, "/dashboard/queue");
    await queueRow(page, "Зарегистрировать ИСХ")
      .getByRole("link", { name: /^Открыть:/ })
      .click();
    const card = side(page);
    await expect(card.getByText(/Передано на регистрацию: Демо Широков/)).toBeVisible();
    // Связь видна из ИСХ: «В ответ на ВХ-109/26» со ссылкой.
    await expect(card.getByText("В ответ на", { exact: true })).toBeVisible();
    await expect(card.getByRole("link", { name: new RegExp(NUMBER) })).toBeVisible();
    await both(page, "outgoing-draft-reply-to");
    await card.getByRole("button", { name: "Зарегистрировать и отправить" }).click();
    await expect(page.getByText(/Письмо зарегистрировано: ИСХ-\d{3}\/26/)).toBeVisible();
    const log = card.getByRole("list", { name: "Журнал отправки" });
    await expect(log.getByRole("listitem").filter({ hasText: "Отправлено" })).toBeVisible({
      timeout: 30_000,
    });
    // Задача ушла сама.
    await spaGoto(page, "/dashboard/queue");
    await expect(queueRow(page, "Зарегистрировать ИСХ")).toHaveCount(0);

    // Исполнитель: уведомление о регистрации, поручение исполнено, ответ виден в блоке «Ответ на письмо».
    await switchTo(page, "universal@demo.example");
    await expect(queueRow(page, `Подготовить ответ на письмо ${NUMBER}`)).toHaveCount(0);
    await spaGoto(page, "/dashboard/queue?panel=open&tab=notifications");
    await expect(page.getByText(/Ответ зарегистрирован: ИСХ-\d{3}\/26/).first()).toBeVisible();
    await spaGoto(page, `/eds/tasks/${encodeURIComponent(NUMBER)}`);
    await expect(page.getByText(/ИСХ-\d{3}\/26 отправлен адресату\./)).toBeVisible();
    await expect(page.getByRole("form", { name: "Отметить исполнение" })).toHaveCount(0);
    await both(page, "task-reply-sent");

    // Директор: ВХ «Исполнено», в карточке ВХ — тот же блок со ссылкой на ИСХ.
    await switchTo(page, "director@demo.example");
    await spaGoto(page, `/eds/inbox/${encodeURIComponent(NUMBER)}`);
    await expect(page.getByRole("heading", { level: 2, name: "Ответ на письмо" })).toBeVisible();
    await expect(page.getByText(/ИСХ-\d{3}\/26 отправлен адресату\./)).toBeVisible();
    await both(page, "inbox-reply-block");
    await spaGoto(page, "/eds/inbox?status=executed");
    await expect(
      page.getByRole("link", { name: `Показать письмо ${NUMBER} в боковом окне` }),
    ).toBeVisible();
  });

  test("письмо не ушло: метка «Не отправлено» в ИСХ и ВХ, уведомления автору и делопроизводителю, «Отправить ещё раз»", async ({
    page,
  }) => {
    test.setTimeout(240_000);
    await incomingWithReplyInstruction(page);
    await executorHandsOver(page, "office@nosmtp.example", false);

    await switchTo(page, "registrar@demo.example");
    await queueRow(page, "Зарегистрировать ИСХ")
      .getByRole("link", { name: /^Открыть:/ })
      .click();
    const card = side(page);
    await card.getByRole("button", { name: "Зарегистрировать и отправить" }).click();
    await expect(
      card.getByText("Не отправлено: Почта не настроена — Настройки · Подключения · Почта"),
    ).toBeVisible({ timeout: 30_000 });
    await expect(card.getByText("Не отправлено", { exact: true })).toBeVisible();
    await both(page, "outgoing-not-sent");
    // Исполнитель тоже знает: уведомление и метка «Не отправлено» в блоке «Ответ на письмо».
    await switchTo(page, "universal@demo.example");
    await spaGoto(page, "/dashboard/queue?panel=open&tab=notifications");
    await expect(page.getByText(/Не отправлено: ИСХ-\d{3}\/26/).first()).toBeVisible();
    await spaGoto(page, `/eds/tasks/${encodeURIComponent(NUMBER)}`);
    const block = page
      .getByRole("heading", { level: 2, name: "Ответ на письмо" })
      .locator(
        "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' ant-card ')][1]",
      );
    await expect(block.getByText("Не отправлено", { exact: true })).toBeVisible();
    await expect(block.getByText(/не ушёл адресату: Почта не настроена/)).toBeVisible();
    await both(page, "task-reply-not-sent");

    // Делопроизводитель тоже получил уведомление и может отправить ещё раз тем же путём — кнопка в карточке ИСХ.
    await switchTo(page, "registrar@demo.example");
    await spaGoto(page, "/dashboard/queue?panel=open&tab=notifications");
    await expect(page.getByText(/Не отправлено: ИСХ-\d{3}\/26/).first()).toBeVisible();
    await spaGoto(page, "/eds/documents?scope=all&kind=letter_out");
    await page
      .getByRole("link", { name: /^Открыть документ:/ })
      .first()
      .click();
    await expect(
      side(page).getByRole("button", { name: "Отправить адресату ещё раз" }),
    ).toBeVisible();
  });
});
