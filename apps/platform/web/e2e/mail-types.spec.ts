import { appendFileSync } from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption } from "./support/fields";

// MAIL-TYPES на MSW: типы входящих писем как справочник с действием по умолчанию. Делопроизводитель видит тег типа
// в списке, фильтрует по типу; у письма «КП поставщика» основная кнопка — «Загрузить прайс», остальные действия — в
// меню; меняет тип одним щелчком. Исполняющий обязанности (все роли, в том числе первая линия почты и администратор) создаёт правило прямо из
// карточки. Администратор настраивает справочник и правила отправителей. Обе ширины, axe (WCAG 2.1 AA), снимки.
// Данные вымышленные; снимки — в docs/screens/mail-types/.
const WIDTHS = [1440, 390] as const;
const REGISTRAR = "registrar@demo.example";
const ADMIN = "admin@demo.example";
// Администратор, которому в «Оргструктуре» выдана и роль первой линии почты (делопроизводитель): правило из карточки.
const CHIEF = ADMIN;
const KEYS = [
  "rt-pf-mock-session",
  "rt-pf-mock-inbound-mail",
  "rt-pf-mock-imap-off",
  "rt-pf-mock-dictionaries",
  "rt-pf-mock-mail-rules",
  "rt-pf-mock-employees",
];
// Сотрудник с ролями «Администратор» (1) и «Делопроизводитель» (7), как после выдачи роли в Оргструктуре.
const ADMIN_WITH_CLERK = {
  id: "u-demo-admin",
  name: "Демо Админов",
  initials: "ДА",
  email: ADMIN,
  position: "Системный администратор",
  role_ids: ["1", "7"],
  access: { crm: true, erp: true },
  status: "active",
  telegram_linked: true,
  erp_sync: "ok",
};

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

// Делопроизводитель, которому выдана ещё и роль снабженца (7 и 4): у него есть право загружать прайсы.
const REGISTRAR_WITH_SUPPLY = {
  id: "u-demo-registrar",
  name: "Демо Канцелярова",
  initials: "ДК",
  email: REGISTRAR,
  position: "Делопроизводитель",
  role_ids: ["7", "4"],
  access: { crm: true, erp: true },
  status: "active",
  telegram_linked: false,
  erp_sync: "ok",
};

async function signInAt(
  page: Page,
  width: number,
  email: string,
  employee?: object,
): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) {
    const clear = KEYS.map((key) => `window.localStorage.removeItem("${key}");`).join(" ");
    await page.evaluate(clear);
  }
  if (employee) {
    await page.goto("/login");
    const employees = JSON.stringify([employee]);
    await page.evaluate(
      `window.localStorage.setItem("rt-pf-mock-employees", ${JSON.stringify(employees)})`,
    );
  }
  await loginAndWait(page, email);
}

for (const width of WIDTHS) {
  test(`@mobile типы писем: список, фильтр, «Передать на загрузку прайса», смена типа · ${String(width)}`, async ({
    page,
  }) => {
    await signInAt(page, width, REGISTRAR);
    await spaGoto(page, "/eds/mail");
    await expect(page.getByRole("heading", { level: 1, name: "Почта" })).toBeVisible();
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

    // письмо с типом «КП поставщика»: у делопроизводителя нет права на каталог — основная кнопка «Передать на загрузку прайса»
    await page.getByRole("link", { name: /Открыть письмо «Коммерческое предложение/ }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Коммерческое предложение на скрепления КБ-65" }),
    ).toBeVisible();
    const primary = page.getByRole("button", { name: "Передать на загрузку прайса" });
    await expect(primary).toBeVisible();
    await expect(page.getByRole("button", { name: "Загрузить прайс", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Создать лид" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Другое действие/ })).toBeVisible();
    await expectNoViolations(page, "карточка КП поставщика");
    await expectFits(page, "карточка КП поставщика");
    await settledScreenshot(page, "mail-types-card-price", "Тип письма");

    // смена типа одним щелчком: основная кнопка следует за типом
    await chooseOption(page.getByRole("combobox", { name: "Сменить тип" }), "Запрос клиента");
    await expect(page.getByText("Тип изменён").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Создать лид" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Передать на загрузку прайса" })).toHaveCount(0);
    await expect(page.getByText("выбрал сотрудник")).toBeVisible();
    await expect(page.getByText(/сменил тип — Запрос клиента/)).toBeVisible();
    await settledScreenshot(page, "mail-types-card-changed", "Тип письма");

    // вернули «КП поставщика» и передали снабженцу: письмо ушло из «Новых»
    await chooseOption(
      page.getByRole("combobox", { name: "Сменить тип" }),
      "КП или прайс поставщика",
    );
    await page.getByRole("button", { name: "Передать на загрузку прайса" }).click();
    await expect(page.getByText("Демо Снабженцев")).toBeVisible();
    await settledScreenshot(page, "mail-types-price-handover", "Тип письма");
    await page.getByRole("button", { name: "Передать на загрузку", exact: true }).click();
    await expect(
      page.getByText("Письмо передано на загрузку прайса: Демо Снабженцев"),
    ).toBeVisible();
    const queue = page.getByRole("list", { name: "Письма, ждущие разбора" });
    await expect(queue.getByText("Коммерческое предложение на скрепления КБ-65")).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Новые · 5" })).toBeVisible();
    await expectNoViolations(page, "список после оформления");
  });

  test(`типы писем: «Загрузить прайс» при праве на каталог, итог «Прайс загружен» и возврат · ${String(width)}`, async ({
    page,
  }) => {
    await signInAt(page, width, REGISTRAR, REGISTRAR_WITH_SUPPLY);
    await spaGoto(page, "/eds/mail/28");
    await expect(
      page.getByRole("heading", { level: 1, name: "Коммерческое предложение на скрепления КБ-65" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Загрузить прайс", exact: true }).click();
    await expect(page.getByRole("link", { name: "Открыть загрузку прайса" })).toHaveAttribute(
      "href",
      "/erp/catalog?part=import",
    );
    await settledScreenshot(page, "mail-types-price-step", "Тип письма");
    await page.getByRole("button", { name: "Прайс загружен — убрать из очереди" }).click();
    await expect(page.getByText("Письмо разобрано: прайс загружен")).toBeVisible();
    await spaGoto(page, "/eds/mail?tab=done");
    const done = page.getByRole("list", { name: "Разобранные письма" });
    const row = done.getByRole("listitem").filter({ hasText: "Коммерческое предложение" });
    await expect(row).toContainText("Прайс загружен");
    // ошибочно закрытое письмо не потеряно: его можно вернуть в «Новые»
    await row.getByRole("button", { name: "Вернуть в Новые" }).click();
    await expect(page.getByText("Письмо вернулось в «Новые»")).toBeVisible();
    await expectNoViolations(page, "после возврата письма");
  });

  test(`типы писем: переданное письмо закрывает снабженец и бухгалтер — отдельные сотрудники без первой линии · ${String(width)}`, async ({
    page,
  }) => {
    await signInAt(page, width, REGISTRAR);
    await spaGoto(page, "/eds/mail/28");
    await page.getByRole("button", { name: "Передать на загрузку прайса" }).click();
    await page.getByRole("button", { name: "Передать на загрузку", exact: true }).click();
    await expect(
      page.getByText("Письмо передано на загрузку прайса: Демо Снабженцев"),
    ).toBeVisible();
    await spaGoto(page, "/eds/mail/18");
    await chooseOption(page.getByRole("combobox", { name: "Сменить тип" }), "Счёт поставщика");
    await page.getByRole("button", { name: "Передать бухгалтеру" }).first().click();
    await page.getByRole("button", { name: "Передать", exact: true }).click();
    await expect(page.getByText("Письмо передано: Демо Бухгалтеров")).toBeVisible();

    // отдельный снабженец (только роль SUPPLY): письмо у него, закрывает он сам
    await page.evaluate('window.localStorage.removeItem("rt-pf-mock-session")');
    await page.goto("/login");
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/eds/my-mail/28");
    await expect(
      page.getByRole("heading", { level: 1, name: "Коммерческое предложение на скрепления КБ-65" }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Открыть загрузку прайса" })).toBeVisible();
    await settledScreenshot(page, "mail-types-own-supply");
    await expectNoViolations(page, "переданное письмо у снабженца");
    await page.getByRole("button", { name: "Прайс загружен — убрать из очереди" }).click();
    await expect(page.getByText("Письмо разобрано: прайс загружен")).toBeVisible();

    // отдельный бухгалтер: «Готово — убрать из очереди»
    await page.evaluate('window.localStorage.removeItem("rt-pf-mock-session")');
    await page.goto("/login");
    await loginAndWait(page, "accountant@demo.example");
    await spaGoto(page, "/eds/my-mail/18");
    await expect(page.getByRole("button", { name: "Готово — убрать из очереди" })).toBeVisible();
    await settledScreenshot(page, "mail-types-own-accountant");
    await expectNoViolations(page, "переданное письмо у бухгалтера");
    await page.getByRole("button", { name: "Готово — убрать из очереди" }).click();
    await expect(page.getByText("Письмо убрано из очереди")).toBeVisible();
  });

  test(`типы писем: правило отправителя из карточки · ${String(width)}`, async ({ page }) => {
    await signInAt(page, width, CHIEF, ADMIN_WITH_CLERK);
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
    // письмо без отметки почтового сервера: пометка, почему тип по правилу не поставлен
    await expect(page.getByText(/Нельзя проверить отправителя/)).toBeVisible();
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
    // таблица не шире окна: названия и «Цвет» не обрезаются, горизонтальной прокрутки таблицы нет
    const clipped = await page.evaluate<number>(
      `(() => { const el = document.querySelector(".pf-co-table-wrap"); return el ? el.scrollWidth - el.clientWidth : 0; })()`,
    );
    // на 390 таблица прокручивается в своём окне (так задумано); на широком экране обрезки быть не должно
    if (width >= 1000) expect(clipped, "таблица типов шире окна").toBeLessThanOrEqual(0);
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
