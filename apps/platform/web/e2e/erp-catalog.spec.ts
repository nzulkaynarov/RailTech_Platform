import { appendFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import {
  loginAndWait,
  openAvatarMenu,
  settledScreenshot,
  spaGoto,
  waitForMotionEnd,
} from "./support/app";

// Расчёт · Номенклатура и поставщики и Техдокументация на MSW (D2-3). Снабженец: находит позицию, открывает поставщика с ценами
// и сроком цены, подаёт запрос на категорию; директор (company.settings) одобряет его; гл. инженер: бригады со ставками,
// загрузка PDF с привязкой к позиции и просмотр файла (страницы в canvas), скачивание; роль без supplier_prices не видит
// цен поставщиков; axe (WCAG 2.1 AA) на каждом экране; снимки 1440 и 390 для PR.

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const found = results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
  );
  // Журнал проверок для PR (docs/screens/D2-3/axe-results.txt): E2E_AXE_LOG=<файл>.
  const log = process.env["E2E_AXE_LOG"];
  if (log) {
    const width = page.viewportSize()?.width ?? 0;
    appendFileSync(log, `${context} · ${String(width)} px: нарушений ${String(found.length)}\n`);
  }
  expect(found, context).toEqual([]);
}

async function signOut(page: Page): Promise<void> {
  await openAvatarMenu(page);
  await page.getByRole("menuitem", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login/);
}

/** Вариант раскрытого списка antd: настоящие строки — `.ant-select-item-option` (роль `option` у виртуального списка скрыта). */
async function pickOption(page: Page, text: string | RegExp): Promise<void> {
  await page.locator(".ant-select-item-option").filter({ hasText: text }).first().click();
}

/** Переключатель `Segmented`: радио скрыто, нажимается подпись. */
async function pickPart(page: Page, name: string): Promise<void> {
  await page.locator("label.ant-segmented-item").filter({ hasText: name }).click();
}

async function openCatalog(page: Page, query = ""): Promise<void> {
  await spaGoto(page, `/erp/catalog${query}`);
  await expect(
    page.getByRole("heading", { level: 1, name: "Номенклатура и поставщики" }),
  ).toBeVisible();
}

async function openDocs(page: Page, query = ""): Promise<void> {
  await spaGoto(page, `/erp/docs${query}`);
  await expect(page.getByRole("heading", { level: 1, name: "Техдокументация" })).toBeVisible();
}

/** Минимальный корректный PDF с латинским текстом и рамкой (файл-образец, не чертёж). */
function samplePdf(): Buffer {
  const stream =
    "BT /F1 18 Tf 60 760 Td (SAMPLE: wiring diagram placeholder) Tj ET\n60 400 300 200 re f";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${String(stream.length)} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let out = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((body, index) => {
    offsets.push(out.length);
    out += `${String(index + 1)} 0 obj\n${body}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${String(objects.length + 1)}\n0000000000 65535 f \n`;
  for (const offset of offsets) out += `${String(offset).padStart(10, "0")} 00000 n \n`;
  out += `trailer\n<< /Size ${String(objects.length + 1)} /Root 1 0 R >>\nstartxref\n${String(xref)}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

/** Часть интерфейса canvas, которую читает проверка (в tsconfig e2e нет типов DOM). */
interface CanvasLike {
  width: number;
  height: number;
  getContext(kind: "2d"): {
    getImageData(x: number, y: number, w: number, h: number): { data: Uint8ClampedArray };
  } | null;
}

/** На canvas первой страницы есть тёмные пиксели: PDF действительно нарисован, а не пустой лист. */
async function expectPdfDrawn(page: Page): Promise<void> {
  const pages = page.getByTestId("pdf-pages");
  await expect(pages.locator("canvas").first()).toBeVisible();
  await expect
    .poll(
      () =>
        pages
          .locator("canvas")
          .first()
          .evaluate((node) => {
            const canvas = node as unknown as CanvasLike;
            const data = canvas
              .getContext("2d")
              ?.getImageData(0, 0, canvas.width, canvas.height).data;
            if (!data) return 0;
            let dark = 0;
            for (let i = 0; i < data.length; i += 4) {
              if ((data[i] ?? 255) < 128 && (data[i + 3] ?? 0) > 0) dark += 1;
            }
            return dark;
          }),
      { timeout: 15_000 },
    )
    .toBeGreaterThan(50);
}

test.describe("Номенклатура и поставщики", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; телефон — отдельный блок @mobile");

  test("снабженец находит позицию, открывает поставщика с ценой и сроком, подаёт запрос на категорию; директор одобряет", async ({
    page,
  }) => {
    await loginAndWait(page, "supply@demo.example");
    await page
      .getByRole("navigation", { name: "Модули" })
      .getByRole("link", { name: "Расчёт" })
      .click();
    await page.getByRole("link", { name: "Номенклатура и поставщики" }).first().click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Номенклатура и поставщики" }),
    ).toBeVisible();

    // поиск и тип
    await page.getByLabel("Поиск по названию, артикулу и чертежу").fill("кабель");
    const open = page.getByRole("button", { name: /Открыть позицию Кабель силовой/ });
    await expect(open).toBeVisible();
    await expect(page.getByRole("button", { name: /Открыть позицию Реле/ })).toHaveCount(0);
    await expectNoViolations(page, "номенклатура");
    await settledScreenshot(page, "catalog-items");

    // карточка позиции: предложения с ценой, квотой и сроком цены
    await open.click();
    const card = page.getByRole("dialog", { name: "Кабель силовой ВВГнг 3×2,5" });
    await expect(card.getByText("ООО «Поставщик Север»")).toBeVisible();
    await expect(card.getByText(/12,50\s*USD/)).toBeVisible();
    await expect(card.getByText("500 шт., от 10")).toBeVisible();
    await expect(card.getByText("Скоро истекает")).toBeVisible();
    await expectNoViolations(page, "карточка позиции");
    await settledScreenshot(page, "catalog-item-prices");

    // переход к поставщику из предложения
    await card.getByRole("button", { name: "Открыть поставщика ООО «Поставщик Север»" }).click();
    const supplier = page.getByRole("dialog", { name: "ООО «Поставщик Север»" });
    await expect(supplier.getByText(/310\s*USD/)).toBeVisible();
    await expect(supplier.getByText("Цена действует", { exact: true }).first()).toBeVisible();
    await expectNoViolations(page, "поставщик");
    await settledScreenshot(page, "catalog-supplier");
    await supplier
      .getByRole("button", { name: /Закрыть|Close/ })
      .first()
      .click();

    // запрос на новую категорию
    await page.getByRole("tab", { name: /Запросы на категории/ }).click();
    await page.getByRole("button", { name: "Запросить категорию" }).click();
    const form = page.getByRole("dialog", { name: "Запросить новую категорию" });
    await form.getByLabel("Название категории").fill("Кабельные лотки");
    await form.getByLabel("Зачем нужна").fill("Кабельные лотки не попадают ни в одну категорию");
    await expect(form.getByText("Что произойдёт")).toBeVisible();
    await form.getByRole("button", { name: "Отправить запрос" }).click();
    await expect(page.getByRole("cell", { name: "Кабельные лотки", exact: true })).toBeVisible();
    // снабженец решения не принимает
    await expect(page.getByRole("button", { name: /Одобрить запрос/ })).toHaveCount(0);
    await settledScreenshot(page, "catalog-requests");

    // директор одобряет, привязав заведённую категорию
    await signOut(page);
    await loginAndWait(page, "director@demo.example");
    await openCatalog(page, "?part=requests");
    await page.getByRole("button", { name: "Одобрить запрос «Кабельные лотки»" }).click();
    const decision = page.getByRole("dialog", { name: /Одобрить запрос/ });
    await decision.getByLabel("Категория, которую вы завели для запроса").click();
    await pickOption(page, "Электрооборудование");
    await decision.getByRole("button", { name: /Одобрить$/ }).click();
    await expect(page.getByText("Одобрен").first()).toBeVisible();
  });

  test("гл. инженер: цен поставщиков нет, сказано словами; бригады со ставками; справочники", async ({
    page,
  }) => {
    await loginAndWait(page, "engineer@demo.example");
    await openCatalog(page, "?part=suppliers&supplier=1");
    const supplier = page.getByRole("dialog", { name: "ООО «Поставщик Север»" });
    await expect(supplier.getByText("Кабель силовой ВВГнг 3×2,5")).toBeVisible();
    await expect(supplier.getByText(/Цены поставщиков вам не показываются/)).toBeVisible();
    await expect(supplier.getByText(/12,50\s*USD/)).toHaveCount(0);
    await expect(supplier.getByText("500 шт., от 10")).toBeVisible();
    await expectNoViolations(page, "поставщик без цен");
    await settledScreenshot(page, "catalog-supplier-no-prices");

    await openCatalog(page, "?part=brigades");
    const first = page.getByRole("row", { name: /Бригада монтажа №1/ });
    await expect(first.getByText(/900\s*000/)).toBeVisible();
    await expect(page.getByText(/Ставки бригад вам не показываются/)).toHaveCount(0);
    await expectNoViolations(page, "бригады");
    await settledScreenshot(page, "catalog-brigades");

    await openCatalog(page, "?part=refs");
    await expect(page.getByRole("radio", { name: "Курсы валют" })).toBeChecked();
    await expect(page.getByRole("cell", { name: "12650.5" })).toBeVisible();
    await expectNoViolations(page, "справочники: курсы");
    await settledScreenshot(page, "catalog-refs");
    await pickPart(page, "Коды ТН ВЭД");
    await expect(page.getByRole("cell", { name: "Провода и кабели изолированные" })).toBeVisible();
    await pickPart(page, "Производители");
    await expect(page.getByRole("cell", { name: "Электрокабель-Тест" })).toBeVisible();
    await expectNoViolations(page, "справочники: производители");
  });

  test("менеджер читает справочники и бригады без цен и ставок", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await openCatalog(page, "?part=brigades");
    await expect(page.getByText("Бригада монтажа №1")).toBeVisible();
    await expect(page.getByText(/Ставки бригад вам не показываются/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Добавить бригаду" })).toHaveCount(0);
    await expect(page.getByText(/900\s*000/)).toHaveCount(0);
    await expectNoViolations(page, "бригады менеджера");
  });
});

test.describe("Техдокументация", () => {
  test.skip(({ isMobile }) => isMobile, "сценарии на десктопе; телефон — отдельный блок @mobile");

  test("гл. инженер загружает PDF с привязкой к позиции, открывает его и скачивает", async ({
    page,
  }) => {
    await loginAndWait(page, "engineer@demo.example");
    await openDocs(page);
    await expect(
      page.getByRole("button", { name: /Открыть файл «Чертёж рельса Р65»/ }),
    ).toBeVisible();
    await expectNoViolations(page, "техдокументация");
    await settledScreenshot(page, "docs-list");

    await page.getByRole("button", { name: "Загрузить файл" }).click();
    const form = page.getByRole("dialog", { name: "Загрузить файл" });
    await form
      .getByLabel("Файл")
      .setInputFiles({ name: "wiring.pdf", mimeType: "application/pdf", buffer: samplePdf() });
    await form.getByLabel("Название").fill("Схема подключения реле РЗ-1");
    await form.getByLabel("Позиция номенклатуры").click();
    await pickOption(page, /Реле защиты РЗ-1/);
    await expect(form.getByRole("button", { name: "Загрузить" })).toBeEnabled();
    await form.getByRole("button", { name: "Загрузить" }).click();

    const link = page.getByRole("button", { name: "Открыть файл «Схема подключения реле РЗ-1»" });
    await expect(link).toBeVisible();
    await link.click();
    const drawer = page.getByRole("dialog", { name: "Схема подключения реле РЗ-1" });
    await expect(drawer.getByText("Реле защиты РЗ-1")).toBeVisible();
    await expect(
      drawer.getByText(/Отправить клиенту в чат: появится вместе с разделом «Чаты»/),
    ).toBeVisible();
    await expectPdfDrawn(page);
    await expectNoViolations(page, "просмотр PDF");
    await settledScreenshot(page, "docs-pdf-preview");

    const download = page.waitForEvent("download");
    await drawer.getByRole("button", { name: "Скачать" }).click();
    expect((await download).suggestedFilename()).toBe("wiring.pdf");

    // файл виден и в карточке позиции
    await drawer
      .getByRole("button", { name: /Закрыть|Close/ })
      .first()
      .click();
    await openCatalog(page, "?part=items&item=2");
    const item = page.getByRole("dialog", { name: "Реле защиты РЗ-1" });
    await expect(item.getByRole("link", { name: "Схема подключения реле РЗ-1" })).toBeVisible();
  });

  test("слишком большой файл отсекается словами, менеджер только читает", async ({ page }) => {
    await loginAndWait(page, "engineer@demo.example");
    await openDocs(page, "?product_id=1");
    await page.getByRole("button", { name: "Загрузить файл" }).click();
    const form = page.getByRole("dialog", { name: "Загрузить файл" });
    await form.getByLabel("Файл").setInputFiles({
      name: "huge.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.alloc(21 * 1024 * 1024, 37),
    });
    await expect(form.getByRole("alert")).toContainText("Файл больше 20 МБ");
    await expect(form.getByRole("button", { name: "Загрузить" })).toBeDisabled();
    await form.getByRole("button", { name: "Отмена" }).click();

    await signOut(page);
    await loginAndWait(page, "manager@demo.example");
    await openDocs(page);
    await expect(
      page.getByRole("button", { name: /Открыть файл «Чертёж рельса Р65»/ }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Загрузить файл" })).toHaveCount(0);
  });
});

test.describe("Номенклатура и техдокументация на телефоне @mobile", () => {
  test("карточки вместо таблиц, окна на всю ширину, PDF в просмотре", async ({ page }) => {
    // проект chromium (CI гоняет оба проекта) открывает тест на 1440: ширину задаёт сам сценарий
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "supply@demo.example");

    await openCatalog(page);
    await expect(page.getByRole("button", { name: /Открыть позицию Кабель/ })).toBeVisible();
    await expect(page.getByRole("table")).toHaveCount(0);
    await expectNoViolations(page, "номенклатура 390");
    await settledScreenshot(page, "catalog-items");

    await page.getByRole("button", { name: /Открыть позицию Кабель/ }).click();
    const card = page.getByRole("dialog", { name: "Кабель силовой ВВГнг 3×2,5" });
    await expect(card.getByText(/12,50\s*USD/)).toBeVisible();
    await expectNoViolations(page, "карточка 390");
    await settledScreenshot(page, "catalog-item-prices");

    await openCatalog(page, "?part=suppliers&supplier=2");
    await expect(page.getByRole("dialog", { name: "АО «Южный Металл»" })).toBeVisible();
    await expectNoViolations(page, "поставщик 390");
    await settledScreenshot(page, "catalog-supplier");

    await openCatalog(page, "?part=refs");
    await expect(page.getByRole("radio", { name: "Курсы валют" })).toBeChecked();
    await expectNoViolations(page, "справочники 390");
    await settledScreenshot(page, "catalog-refs");

    await openDocs(page, "?doc=2");
    const drawer = page.getByRole("dialog", { name: "Чертёж рельса Р65" });
    await expect(drawer).toBeVisible();
    await expectPdfDrawn(page);
    await expectNoViolations(page, "просмотр PDF 390");
    await settledScreenshot(page, "docs-pdf-preview");
  });
});
