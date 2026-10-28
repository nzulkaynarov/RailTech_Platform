import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// «Мои задачи», поиск и колокольчик без тупиков (W15-H2, UX-оценка P0-3, P1-8, P2-9) на MSW: строка с экраном — «Открыть»
// (primary у всех срочных; строки лидов — «Ждут ответа», D1-6), строка без экрана — «Где сделать», пустые состояния по ролям, частичный результат при отказе
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

const STUB = "rt-pf-mock-queue-stub";
const ROW_STUB = "Где сделать: Разобраться с проектом ПР-2026-099";

/** Директору — строка очереди без родного экрана (проект): у лидов, писем, КП и служебок экраны уже есть (D1-6). */
async function showStubRow(page: Page): Promise<void> {
  await loginAndWait(page, "director@demo.example");
  await setMock(page, STUB, "1");
  await page.reload();
}

const SIDE = { name: "Боковое окно" } as const;

test.describe("Мои задачи: «Открыть» или «Где сделать»", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("директор: строка без экрана — «Где сделать» с мостом в старый ERP, ссылки на заглушку нет", async ({
    page,
  }) => {
    await showStubRow(page);
    const queue = page.getByRole("region", { name: "Что сделать сейчас" });
    await queue.getByRole("button", { name: ROW_STUB }).click();
    const pop = page.getByRole("region", { name: "Где сделать" });
    await expect(pop.getByText(/Сейчас — в старом ERP: раздел «Сделки»/)).toBeVisible();
    const open = pop.getByRole("link", { name: /Открыть в старом ERP/ });
    await expect(open).toHaveAttribute("href", "http://erp.localhost:8088/#crm-deals");
    await expect(open).toHaveAttribute("target", "_blank");
    expect(await open.getAttribute("rel")).toContain("noopener");
    await expect(pop.getByText("Когда появится: к пилоту.")).toBeVisible();
    // письмо, КП и служебка рядом — «Открыть», «Где сделать» нет; плюс просроченный заказ поставщику (D2-2)
    await expect(queue.getByRole("link", { name: /^Открыть:/ })).toHaveCount(4);
    await expect(queue.getByRole("button", { name: /^Где сделать/ })).toHaveCount(1);
    await shoot(page, "queue-where");
  });

  test("с клавиатуры: Enter на «Где сделать» → фокус в секции → Tab доходит до «Открыть в …» → Escape возвращает на кнопку", async ({
    page,
  }) => {
    await showStubRow(page);
    const button = page.getByRole("button", { name: ROW_STUB });
    await button.focus();
    await page.keyboard.press("Enter");

    const panel = page.getByRole("region", { name: "Где сделать" });
    await expect(panel).toBeFocused();
    const link = panel.getByRole("link", { name: /Открыть в старом ERP/ });
    await expect(link).toBeVisible(); // адрес старого ERP приходит из BFF — Tab после его появления
    await page.keyboard.press("Tab");
    await expect(link).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(button).toBeFocused();
    await expect(button).toHaveAttribute("aria-expanded", "false");
  });

  test("директор: письмо, КП и служебка (родные экраны) — «Открыть» открывает объект в боковом окне на вкладке решения; primary у срочных писем", async ({
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
    await expect(queue.getByRole("button", { name: /^Где сделать/ })).toHaveCount(0);
    await settledScreenshot(page, "queue-director");

    const cases = [
      {
        row: /Открыть: Наложить резолюцию на письмо ВХ-104/,
        url: /\/eds\/inbox\/%D0%92%D0%A5-104%2F26\?panel=open&tab=resolution$/,
        heading: "Письмо ВХ-104/26",
        tab: "Резолюция",
      },
      {
        row: /Открыть: Одобрить КП-2026\/118/,
        url: /\/eds\/drafts\/%D0%9A%D0%9F-2026%2F118\?panel=open&tab=approve$/,
        heading: "КП-2026/118",
        tab: "Одобрение",
      },
      {
        row: /Открыть: Согласовать СЗ-2026\/031/,
        url: /\/eds\/approvals\/%D0%A1%D0%97-2026%2F031\?panel=open&tab=agree$/,
        heading: "СЗ-2026/031",
        tab: "Согласование",
      },
    ];
    for (const item of cases) {
      await spaGoto(page, "/dashboard/queue");
      await page
        .getByRole("region", { name: "Что сделать сейчас" })
        .getByRole("link", { name: item.row })
        .click();
      await expect(page).toHaveURL(item.url);
      await expect(page.getByRole("heading", { level: 1, name: item.heading })).toBeVisible();
      await expect(
        page.getByRole("complementary", SIDE).getByRole("tab", { name: item.tab, selected: true }),
      ).toBeVisible();
    }
  });

  test("менеджер: передача и сообщение клиента открывают диалог в «Ждут ответа» — «Открыть», без «Где сделать»", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    const queue = page.getByRole("region", { name: "Что сделать сейчас" });
    const take = queue.getByRole("link", { name: "Открыть: Взять в работу лида L-2041" });
    await expect(take).toHaveClass(/ant-btn-primary/);
    await expect(queue.getByRole("button", { name: /^Где сделать/ })).toHaveCount(0);
    await settledScreenshot(page, "queue-manager");

    await take.click();
    await expect(page).toHaveURL(/\/crm\/messages\?lead=L-2041$/);
    await expect(page.getByRole("heading", { level: 1, name: "Ждут ответа" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "Азиз Демо" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Забрать/ }).first()).toBeVisible();
    await expectNoViolations(page, "диалог из очереди");
  });
});

test.describe("Мои задачи: пустые состояния и частичный результат", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("accountant@demo.example: пустая очередь своими словами", async ({ page }) => {
    await loginAndWait(page, "accountant@demo.example");
    await expect(
      page.getByRole("main").getByText("Платёжек на подтверждение и счетов к выставлению нет"),
    ).toBeVisible();
    await expect(page.getByText("Решений от вас пока не требуется")).toHaveCount(0);
    await shoot(page, "queue-empty-accountant");
  });

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

test.describe("Мои задачи: EDS не отвечает", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("директор: КП и остальное показаны, плашка называет «Документы», писем и служебок нет", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await setMock(page, "rt-pf-mock-eds-down", "1");
    await page.reload();
    const main = page.getByRole("main");
    await expect(main.getByText("Одобрить КП-2026/118 (черновик)")).toBeVisible();
    await expect(main.getByRole("status").first()).toContainText(
      "Не загрузились письма и документы: раздел «Документы» не ответил. Остальное показано.",
    );
    await expect(main.getByText(/Наложить резолюцию на письмо/)).toHaveCount(0);
    await shoot(page, "queue-partial-eds");
  });
});

test.describe("Поиск: объект, «Где посмотреть», действия", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("менеджер: результат без экрана — «Где посмотреть» с мостом, адрес не меняется", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    const search = page.getByRole("combobox", { name: "Глобальный поиск" });
    // «Лиды» — настоящий экран (D1-2b); без экрана — заявки (раздел «Заявки», старый ERP)
    await search.fill("ЗВ-2026-104");
    await page.getByRole("option", { name: /ЗВ-2026-104/ }).click();
    const where = page.getByRole("region", { name: "Где посмотреть" });
    await expect(where.getByRole("link", { name: /Открыть в старом ERP/ })).toHaveAttribute(
      "href",
      "http://erp.localhost:8088/#crm-deals",
    );
    await expect(page).toHaveURL(/\/dashboard\/queue/);
    await shoot(page, "search-where");
    // Escape внутри подсказки закрывает её и возвращает фокус в поле поиска
    await where.getByRole("link", { name: /Открыть в старом ERP/ }).focus();
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
    // «Создать заявку» — настоящий экран (D1-2b): действие ведёт к лидам «Просят КП»
    await action.click();
    await expect(page).toHaveURL(/\/crm\/leads\?status=wants_quote$/);

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

/** Объекты D1: адрес, заголовок экрана и выбранная вкладка бокового окна (SPEC-v3 §6.3, §6.4). */
const OBJECTS = {
  letter: {
    path: /\/eds\/inbox\/%D0%92%D0%A5-104%2F26\?/,
    url: /\/eds\/inbox\/%D0%92%D0%A5-104%2F26\?panel=open&tab=resolution$/,
    heading: "Письмо ВХ-104/26",
    tab: "Резолюция",
    sheet: /^Резолюция/,
  },
  quote: {
    path: /\/eds\/drafts\/%D0%9A%D0%9F-2026%2F118\?/,
    url: /\/eds\/drafts\/%D0%9A%D0%9F-2026%2F118\?panel=open&tab=approve$/,
    heading: "КП-2026/118",
    tab: "Одобрение",
    sheet: /^Одобрение/,
  },
  memo: {
    path: /\/eds\/approvals\/%D0%A1%D0%97-2026%2F031\?/,
    url: /\/eds\/approvals\/%D0%A1%D0%97-2026%2F031\?panel=open&tab=agree$/,
    heading: "СЗ-2026/031",
    tab: "Согласование",
    sheet: /^Согласование/,
  },
} as const;

async function expectOpened(page: Page, key: keyof typeof OBJECTS): Promise<void> {
  const object = OBJECTS[key];
  await expect(page).toHaveURL(object.url);
  await expect(page.getByRole("heading", { level: 1, name: object.heading })).toBeVisible();
  await expect(
    page.getByRole("complementary", SIDE).getByRole("tab", { name: object.tab, selected: true }),
  ).toBeVisible();
}

test.describe("Поиск ⌘K: письмо, КП и служебка открываются в боковом окне", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const [query, option, key] of [
    ["ВХ-104/26", /Письмо ВХ-104\/26/, "letter"],
    ["КП-2026/118", /КП-2026\/118/, "quote"],
    ["СЗ-2026/031", /СЗ-2026\/031/, "memo"],
  ] as const) {
    test(`директор: «${query}» → вкладка «${OBJECTS[key].tab}», «Где посмотреть» нет`, async ({
      page,
    }) => {
      await loginAndWait(page, "director@demo.example");
      const search = page.getByRole("combobox", { name: "Глобальный поиск" });
      await search.fill(query);
      await expectNoViolations(page, `поиск ${query}`);
      await page.getByRole("option", { name: option }).click();
      await expectOpened(page, key);
      await expect(page.getByRole("region", { name: "Где посмотреть" })).toHaveCount(0);
    });
  }
});

test.describe("Колокольчик: объект с экраном открывается на нужной вкладке", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const [title, key] of [
    [/Письмо ВХ-104\/26 ждёт резолюции/, "letter"],
    [/КП-2026\/118 ждёт вашего согласования/, "quote"],
    [/СЗ-2026\/031 на согласовании/, "memo"],
  ] as const) {
    test(`директор: ${String(title)} → «${OBJECTS[key].tab}»`, async ({ page }) => {
      await loginAndWait(page, "director@demo.example");
      await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
      const center = page.getByRole("dialog", { name: "Центр уведомлений" });
      await center.getByRole("link", { name: title }).click();
      await expectOpened(page, key);
      if (key === "letter") await settledScreenshot(page, "bell-opened-letter");
    });
  }

  test("менеджер: передача бота из колокольчика открывает диалог в «Ждут ответа»", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
    const center = page.getByRole("dialog", { name: "Центр уведомлений" });
    await center.getByRole("link", { name: /Лид L-2041 просит КП/ }).click();
    await expect(page).toHaveURL(/\/crm\/messages\?lead=L-2041$/);
    await expect(page.getByRole("heading", { level: 2, name: "Азиз Демо" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Где посмотреть" })).toHaveCount(0);
  });
});

test.describe("Переходы на телефоне @mobile", () => {
  test("@mobile директор: из очереди письмо, КП и служебка открываются листом на весь экран; менеджер — диалогом", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    await settledScreenshot(page, "queue-director-mobile");
    for (const [row, key] of [
      [/Открыть: Наложить резолюцию на письмо ВХ-104/, "letter"],
      [/Открыть: Одобрить КП-2026\/118/, "quote"],
      [/Открыть: Согласовать СЗ-2026\/031/, "memo"],
    ] as const) {
      await spaGoto(page, "/dashboard/queue");
      await page
        .getByRole("region", { name: "Что сделать сейчас" })
        .getByRole("link", { name: row })
        .click();
      // на телефоне `panel=open` становится листом (`sheet=`): адрес проверяем по объекту, а не по окну
      await expect(page).toHaveURL(OBJECTS[key].path);
      const sheet = page.getByRole("dialog", { name: OBJECTS[key].sheet });
      await expect(sheet).toBeVisible();
      const box = await sheet.boundingBox();
      expect(box?.width).toBeGreaterThanOrEqual(389);
      expect(box?.height).toBeGreaterThanOrEqual(843);
      await expectNoViolations(page, `лист ${key}`);
    }
  });

  test("@mobile колокольчик и поиск открывают письмо листом «Резолюция»", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "director@demo.example");
    await page.getByRole("button", { name: /^Центр уведомлений/ }).click();
    await page
      .getByRole("dialog", { name: "Центр уведомлений" })
      .getByRole("link", { name: /Письмо ВХ-104\/26 ждёт резолюции/ })
      .click();
    await expect(page).toHaveURL(OBJECTS.letter.path);
    await expect(page.getByRole("dialog", { name: /^Резолюция/ })).toBeVisible();
    await settledScreenshot(page, "bell-opened-letter-mobile");

    await spaGoto(page, "/dashboard/queue");
    await page.getByRole("combobox", { name: "Глобальный поиск" }).fill("КП-2026/118");
    await page.getByRole("option", { name: /КП-2026\/118/ }).click();
    await expect(page).toHaveURL(OBJECTS.quote.path);
    await expect(page.getByRole("dialog", { name: /^Одобрение/ })).toBeVisible();
  });

  test("@mobile менеджер: передача из очереди — диалог на весь экран", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await loginAndWait(page, "manager@demo.example");
    await page
      .getByRole("region", { name: "Что сделать сейчас" })
      .getByRole("link", { name: "Открыть: Взять в работу лида L-2041" })
      .click();
    await expect(page).toHaveURL(/\/crm\/messages\?lead=L-2041$/);
    await expect(page.getByRole("heading", { level: 2, name: "Азиз Демо" })).toBeVisible();
    await settledScreenshot(page, "queue-manager-dialog-mobile");
    await expectNoViolations(page, "диалог на телефоне");
  });
});
