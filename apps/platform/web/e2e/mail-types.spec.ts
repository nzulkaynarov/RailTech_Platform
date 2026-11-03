import { appendFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption } from "./support/fields";

// MAIL-TYPES на MSW: типы входящих писем как справочник с действием по умолчанию. Делопроизводитель видит тег типа
// в списке, фильтрует по типу; у письма «КП поставщика» основная кнопка — «Загрузить прайс», остальные действия — в
// меню; меняет тип одним щелчком. Руководитель канцелярии (первая линия и администратор) создаёт правило прямо из
// карточки. Администратор настраивает справочник и правила отправителей. Обе ширины, axe (WCAG 2.1 AA), снимки.
// Данные вымышленные; снимки — в docs/screens/mail-types/.
const WIDTHS = [1440, 390] as const;
const REGISTRAR = "registrar@demo.example";
const CHIEF = "chief@demo.example";
const ADMIN = "admin@demo.example";
const KEYS = [
  "rt-pf-mock-session",
  "rt-pf-mock-inbound-mail",
  "rt-pf-mock-imap-off",
  "rt-pf-mock-dictionaries",
  "rt-pf-mock-mail-rules",
];

async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const found = results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
  );
  const log = process.env["E2E_AXE_LOG"];
  if (log) {
    const width = page.viewportSize()?.width ?? 0;
    appendFileSync(log, `${context} · ${String(width)} px: нарушений ${String(found.length)}\n`);
  }
  expect(found, context).toEqual([]);
}

/** Снимок страницы целиком (на 390 тип и действия идут под перепиской). */
async function settledScreenshot(page: Page, name: string, focus?: string): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  // На 390 правая колонка карточки — под перепиской, а прокручивается внутренняя область: показываем нужное место.
  if (focus) await page.getByRole("heading", { name: focus }).first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

async function expectFits(page: Page, context: string): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow, context).toBeLessThanOrEqual(0);
}

async function signInAt(page: Page, width: number, email: string): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) {
    const clear = KEYS.map((key) => `window.localStorage.removeItem("${key}");`).join(" ");
    await page.evaluate(clear);
  }
  await loginAndWait(page, email);
}

for (const width of WIDTHS) {
  test(`@mobile типы писем: список, фильтр, «Загрузить прайс», смена типа · ${String(width)}`, async ({
    page,
  }) => {
    await signInAt(page, width, REGISTRAR);
    await spaGoto(page, "/eds/mail");
    await expect(page.getByRole("heading", { level: 1, name: "Входящая почта" })).toBeVisible();
    const list = page.getByRole("list", { name: "Письма, ждущие разбора" });
    // тег типа в строке письма; оформленные письма во «Входящих» не висят — только требующие действия
    await expect(list.getByText("КП или прайс поставщика", { exact: true })).toBeVisible();
    await expect(list.getByText("Рассылка", { exact: true })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Новые · 6" })).toBeVisible();
    await expectNoViolations(page, "список с типами");
    await expectFits(page, "список с типами");
    await settledScreenshot(page, "mail-types-list");

    // фильтр по типу
    await chooseOption(
      page.getByRole("combobox", { name: "Тип письма" }),
      "КП или прайс поставщика",
    );
    await expect(list.getByRole("listitem")).toHaveCount(1);
    await expect(page.getByRole("tab", { name: "Новые · 6" })).toBeVisible();
    await settledScreenshot(page, "mail-types-filter");

    // письмо с типом «КП поставщика»: основная кнопка — «Загрузить прайс»
    await page.getByRole("link", { name: /Открыть письмо «Коммерческое предложение/ }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Коммерческое предложение на скрепления КБ-65" }),
    ).toBeVisible();
    const primary = page.getByRole("button", { name: "Загрузить прайс" });
    await expect(primary).toBeVisible();
    await expect(page.getByRole("button", { name: "Создать лид" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Другое действие/ })).toBeVisible();
    await expectNoViolations(page, "карточка КП поставщика");
    await expectFits(page, "карточка КП поставщика");
    await settledScreenshot(page, "mail-types-card-price", "Тип письма");

    // смена типа одним щелчком: основная кнопка следует за типом
    await chooseOption(page.getByRole("combobox", { name: "Сменить тип" }), "Запрос клиента");
    await expect(page.getByText("Тип изменён").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Создать лид" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Загрузить прайс" })).toHaveCount(0);
    await expect(page.getByText("выбрал сотрудник")).toBeVisible();
    await expect(page.getByText(/сменил тип — Запрос клиента/)).toBeVisible();
    await settledScreenshot(page, "mail-types-card-changed", "Тип письма");

    // вернули «КП поставщика» и закрыли письмо: прайс загружен — письмо ушло из «Новых»
    await chooseOption(
      page.getByRole("combobox", { name: "Сменить тип" }),
      "КП или прайс поставщика",
    );
    await page.getByRole("button", { name: "Загрузить прайс" }).click();
    await expect(page.getByRole("link", { name: "Открыть загрузку прайса" })).toHaveAttribute(
      "href",
      "/erp/catalog?part=import",
    );
    await settledScreenshot(page, "mail-types-price-step", "Тип письма");
    await page.getByRole("button", { name: "Прайс загружен — убрать из очереди" }).click();
    await expect(page.getByText("Письмо разобрано: прайс загружен")).toBeVisible();
    const queue = page.getByRole("list", { name: "Письма, ждущие разбора" });
    await expect(queue.getByText("Коммерческое предложение на скрепления КБ-65")).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Новые · 5" })).toBeVisible();
    await expectNoViolations(page, "список после оформления");
  });

  test(`типы писем: правило отправителя из карточки · ${String(width)}`, async ({ page }) => {
    await signInAt(page, width, CHIEF);
    await spaGoto(page, "/eds/mail/29");
    await expect(
      page.getByRole("heading", { level: 1, name: "Требование о предоставлении документов" }),
    ).toBeVisible();
    await chooseOption(
      page.getByRole("combobox", { name: "Сменить тип" }),
      "Официальное письмо (госорган, банк, налоговая)",
    );
    await expect(page.getByText("Тип изменён").first()).toBeVisible();
    // у «Официального письма» основная кнопка — «Зарегистрировать как ВХ» (форма регистрации), не «Создать лид»
    await expect(page.getByRole("link", { name: "Зарегистрировать как ВХ" })).toHaveAttribute(
      "href",
      "/eds/register?mail=29",
    );
    await expect(page.getByRole("button", { name: "Создать лид" })).toHaveCount(0);
    const rule = page.getByRole("button", { name: /Всегда считать письма от soliq.example/ });
    await expect(rule).toBeVisible();
    await expectNoViolations(page, "карточка с правилом");
    await expectFits(page, "карточка с правилом");
    await settledScreenshot(page, "mail-types-card-rule", "Тип письма");
    await rule.click();
    await expect(page.getByText(/Правило создано/).first()).toBeVisible();
  });

  test(`настройка справочника «Типы входящих писем» и правил · ${String(width)}`, async ({
    page,
  }) => {
    await signInAt(page, width, ADMIN);
    await spaGoto(page, "/admin/dictionaries?list=doc%3Amail-types");
    await expect(page.getByRole("heading", { level: 1, name: "Справочники" })).toBeVisible();
    await expect(page.getByText("Создать лид → менеджеру").first()).toBeVisible();
    await expectNoViolations(page, "справочник типов");
    await expectFits(page, "справочник типов");
    await settledScreenshot(page, "mail-types-settings");

    await page.getByRole("button", { name: "Добавить значение" }).click();
    const dialog = page.getByRole("dialog", { name: "Новое значение" });
    await dialog.getByRole("textbox", { name: "Название по-русски" }).fill("Жалоба покупателя");
    await chooseOption(
      dialog.getByRole("combobox", { name: "Действие по умолчанию" }),
      "Передать бухгалтеру",
    );
    await expectNoViolations(page, "диалог нового типа");
    await settledScreenshot(page, "mail-types-settings-add");
    await dialog.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByText("Жалоба покупателя", { exact: true })).toBeVisible();

    await page.getByRole("textbox", { name: "Адрес или домен" }).fill("*@soliq.uz");
    await chooseOption(
      page.getByRole("combobox", { name: "Тип" }),
      "Официальное письмо (госорган, банк, налоговая)",
    );
    await page.getByRole("button", { name: "Добавить правило" }).click();
    await expect(page.getByText("soliq.uz", { exact: true })).toBeVisible();
    await expectNoViolations(page, "правила отправителей");
    await expectFits(page, "правила отправителей");
    await settledScreenshot(page, "mail-types-settings-rules");
  });
}
