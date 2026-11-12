import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, openAvatarMenu, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption, fillDate, openStep, pickFiles } from "./support/fields";

// P4 «Письмо на бланке» на MSW (SPEC-v3 §3.2a п. 3; план 2026-11-01 §6 п. 6): требование ГНК → поручение «Подготовить ответ»
// исполнителю без права регистрировать → письмо на бланке блоками (абзац, список, таблица) → настоящий PDF (демо — рендер
// `rt-docs`) → «Передать на регистрацию» → делопроизводитель «Зарегистрировать и отправить» → номер ИСХ, журнал отправки,
// поручение закрыто, письмо ВХ «Исполнено». Отдельно — директор с правом регистрировать: «Зарегистрировать и отправить» прямо
// из формы и отказ почты с причиной словами. Снимки 1440 и 390 с axe — E2E_SCREENSHOT_DIR (docs/screens/p4).
const WIDE = 1440;
const NARROW = 390;

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

/** Текущий экран на обеих ширинах (состояние формы сохраняется): снимок, если задан каталог, и axe 0. */
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

function queueRow(page: Page, text: string) {
  return page
    .getByRole("region", { name: "Что сделать сейчас" })
    .getByRole("listitem")
    .filter({ hasText: text });
}

function side(page: Page): Locator {
  return page.locator("#pf-context-panel");
}

/** Письмо в редакторе: абзац, список набором «- », таблица кнопкой (переход по ячейкам — Tab). */
async function fillLetterBody(page: Page): Promise<void> {
  await openStep(page, "Текст и вложения");
  const box = page.getByRole("textbox", { name: "Текст", exact: true });
  await box.click();
  await page.keyboard.type(
    "На требование № 14-02/3381 о представлении пояснений сообщаем: расхождения в декларации по НДС за III квартал вызваны поступлением счетов-фактур после отчётной даты.",
  );
  await page.keyboard.press("Enter");
  await page.keyboard.type("- уточнённая декларация по НДС;");
  await page.keyboard.press("Enter");
  await page.keyboard.type("реестр счетов-фактур партнёров");
  await page.keyboard.press("Enter");
  await page.keyboard.press("Enter");
  await page
    .getByRole("toolbar", { name: "Оформление текста" })
    .getByRole("button", { name: "Таблица" })
    .click();
  for (const [index, value] of [
    "Счёт-фактура",
    "Сумма НДС, сум",
    "",
    "№ 118 от 29.09.2026",
    "14 400 000",
  ].entries()) {
    if (index > 0) await page.keyboard.press("Tab");
    if (value) await page.keyboard.type(value);
  }
  await expect(box.getByRole("list")).toContainText("реестр счетов-фактур партнёров");
}

async function pdfReady(page: Page): Promise<void> {
  const region = page.getByRole("region", { name: "PDF на бланке" });
  await expect(region.getByText(/PDF (с номером ИСХ )?готов · 1 стр\./)).toBeVisible({
    timeout: 15_000,
  });
  // страница нарисована pdf.js в canvas
  await expect(region.getByRole("img", { name: /страница 1 из 1/ })).toBeVisible();
  await region.getByRole("img", { name: /страница 1 из 1/ }).scrollIntoViewIfNeeded();
}

/** Журнал отправки в кадре: итог «Отправлено» и адрес. */
async function logInView(page: Page): Promise<void> {
  // на 390 карточка — лист на весь экран, а не боковое окно
  const log = page.getByRole("list", { name: "Журнал отправки" });
  await expect(log.getByRole("listitem").filter({ hasText: "Отправлено" })).toBeVisible();
  await log.scrollIntoViewIfNeeded();
}

/** Текст письма в карточке: абзац, список и таблица с шапкой (не строки «a | b»); полей «Сумма» и пустых «—» нет. */
async function expectLetterBody(card: Locator): Promise<void> {
  const table = card.getByRole("table", { name: "Таблица в тексте письма" });
  await expect(table.getByRole("columnheader", { name: "Счёт-фактура" })).toBeVisible();
  await expect(table.getByRole("cell", { name: "14 400 000" })).toBeVisible();
  await expect(card.getByText("реестр счетов-фактур партнёров")).toBeVisible();
  await expect(card.getByText(/Счёт-фактура \| Сумма НДС/)).toHaveCount(0);
  await expect(card.locator("dt", { hasText: /^Сумма$/ })).toHaveCount(0);
  await table.scrollIntoViewIfNeeded();
}

test.describe("P4: письмо на бланке", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("ответ на требование ГНК от поручения: черновик исполнителя → PDF → регистрация и отправка → поручение закрыто", async ({
    page,
  }) => {
    test.setTimeout(240_000);
    // 1. Делопроизводитель регистрирует требование ГНК с проектом «Подготовить ответ» исполнителю.
    await at(page, WIDE);
    await loginAndWait(page, "registrar@demo.example");
    await spaGoto(page, "/eds/register");
    await chooseOption(page.getByLabel("Вид документа"), "Требование или уведомление ГНК");
    await page.getByLabel("Корреспондент", { exact: true }).fill("ГНИ Мирабадского района");
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
    await expect(page.getByText(/Зарегистрировано: ВХ-109\/26/)).toBeVisible();

    // 2. Директор утверждает проект резолюции.
    await switchTo(page, "director@demo.example");
    await spaGoto(page, `/eds/inbox/${encodeURIComponent("ВХ-109/26")}?panel=open&tab=resolution`);
    await page.getByRole("button", { name: "Утвердить проект" }).click();
    await expect(page.getByText("Резолюция наложена: поручение ушло исполнителям")).toBeVisible();

    // 3. Исполнитель без права регистрировать: «Подготовить ответ» → письмо на бланке → PDF → «Передать на регистрацию».
    await switchTo(page, "universal@demo.example");
    await queueRow(page, "Подготовить ответ на письмо ВХ-109/26")
      .getByRole("link", { name: /^Открыть:/ })
      .click();
    await page.getByRole("link", { name: "Ответить" }).click();
    await expect(page).toHaveURL(/\/eds\/new\?type=letter&reply_to=/);
    await expect(page.getByLabel("В ответ на входящее")).toHaveValue("ВХ-109/26");
    await page.getByLabel("Тема").fill("Пояснения по требованию № 14-02/3381");
    await page.getByLabel("Адресат (организация)").fill("ГНИ Мирабадского района");
    await page.getByLabel("Почта адресата").fill("gni-mirabad@example.uz");
    await page
      .getByLabel("Кому (должность и ФИО)")
      .fill("Начальнику ГНИ Мирабадского района Каримову А. А.");
    await fillLetterBody(page);
    await openStep(page, "Согласование и подпись");
    await expect(
      page.getByText("Пусто — подписант бланка: Каримов А. А., Директор."),
    ).toBeVisible();
    await both(page, "editor");

    await page.getByRole("button", { name: "Показать PDF" }).click();
    await pdfReady(page);
    await both(page, "pdf-preview", pdfReady);

    await openStep(page, "Проверка и отправка");
    await page.getByRole("button", { name: "Передать на регистрацию" }).click();
    await expect(page.getByText("Передано на регистрацию делопроизводителю.")).toBeVisible();
    await expect(side(page).getByText(/Передано на регистрацию: Демо Широков/)).toBeVisible();

    // 4. Делопроизводитель: черновик в «Все документы» → «Зарегистрировать и отправить».
    await switchTo(page, "registrar@demo.example");
    await spaGoto(page, "/eds/documents?scope=all");
    await page
      .getByRole("link", { name: "Открыть документ: Пояснения по требованию № 14-02/3381" })
      .click();
    const card = side(page);
    await expect(card.getByText(/Передано на регистрацию: Демо Широков/)).toBeVisible();
    await both(page, "handed-over");
    // Карточка письма: тело — теми же блоками, что в редакторе (таблица таблицей), без неприменимой «Суммы».
    await expectLetterBody(card);
    await both(page, "letter-card", async () => {
      // на 390 карточка — лист на весь экран; таблицу ищем на странице (скрытое окно в роли не попадает)
      const table = page.getByRole("table", { name: "Таблица в тексте письма" });
      await expect(table).toBeVisible();
      await table.scrollIntoViewIfNeeded();
    });
    await card.getByRole("button", { name: "Зарегистрировать и отправить" }).click();
    await expect(page.getByText(/Письмо зарегистрировано: ИСХ-\d{3}\/26/)).toBeVisible();
    await expect(card.getByText("Зарегистрировано")).toBeVisible();
    await expectLetterBody(card); // зарегистрированное письмо — тот же вид текста

    // Журнал отправки доходит до «Отправлено» (итог почтового сервиса CRM).
    const log = side(page).getByRole("list", { name: "Журнал отправки" });
    await expect(log.getByRole("listitem").filter({ hasText: "Отправлено" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(log.getByText(/gni-mirabad@example\.uz/)).toBeVisible();
    await both(page, "sent", logInView);

    // 5. Ответ закрыл поручение: письмо ВХ-109/26 «Исполнено».
    await switchTo(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox?status=executed");
    await expect(
      page.getByRole("link", { name: "Показать письмо ВХ-109/26 в боковом окне" }),
    ).toBeVisible();
  });

  test("директор регистрирует и отправляет из формы; почта не настроена — причина словами в журнале отправки", async ({
    page,
  }) => {
    await at(page, WIDE);
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/new?type=letter");
    await page.getByLabel("Тема").fill("О сроках поставки");
    await page.getByLabel("Адресат (организация)").fill("ООО «Демо-Путь»");
    await page.getByLabel("Почта адресата").fill("office@nosmtp.example");
    await openStep(page, "Текст и вложения");
    await page.getByLabel("Текст", { exact: true }).fill("Сообщаем о переносе отгрузки на неделю.");
    await openStep(page, "Проверка и отправка");
    await page.getByRole("button", { name: "Зарегистрировать и отправить" }).click();
    await expect(
      page.getByText(/Письмо зарегистрировано: ИСХ-\d{3}\/26\. Отправляем адресату\./),
    ).toBeVisible();

    await expect(
      side(page).getByText("Не отправлено: Почта не настроена — Настройки · Подключения · Почта"),
    ).toBeVisible({ timeout: 30_000 });
    await expect(
      side(page).getByRole("button", { name: "Отправить адресату ещё раз" }),
    ).toBeVisible();
    await both(page, "mail-failed");
  });
});
