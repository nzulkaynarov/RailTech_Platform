import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// «Задачи», поиск и колокольчик без тупиков (W15-H2, UX-оценка P0-3, P1-8, P2-9) на MSW: строка с экраном — «Открыть»
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

const SIDE = { name: "Боковое окно" } as const;

test.describe("Задачи: «Открыть» или «Где сделать»", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");
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

test.describe("Задачи: пустые состояния и частичный результат", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("accountant@demo.example: платёжка и счёт ждут — очередь не пишет «Платёжек нет» (U1, D2-8)", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    const main = page.getByRole("main");
    await expect(main.getByText("Подтвердить оплату по счёту СЧ-2026/145")).toBeVisible();
    await expect(main.getByText("Выставить счёт СЧ-2026/143")).toBeVisible();
    await expect(
      main.getByText("Платёжек на подтверждение и счетов к выставлению нет"),
    ).toHaveCount(0);
    await expect(page.getByText("Решений от вас пока не требуется")).toHaveCount(0);
    await shoot(page, "queue-accountant");
  });

  test("ERP не отвечает: данные CRM показаны, плашка называет «Документы» и «Расчёт»", async ({
    page,
  }) => {
    await loginAndWait(page, "all@demo.example");
    await setMock(page, "rt-pf-mock-erp-down", "1");
    await page.reload();
    await expect(page.getByRole("main").getByText("Взять в работу лида L-2041")).toBeVisible();
    await expect(page.getByRole("main").getByRole("status")).toContainText(
      "Не загрузились КП, расчёты, счета и проекты: раздел «Операции» не ответил. Остальное показано.",
    );
    await shoot(page, "queue-partial-erp");
  });

  test("CRM не отвечает: данные ERP показаны, плашка называет «Клиенты»", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await setMock(page, "rt-pf-mock-crm-down", "1");
    await page.reload();
    await expect(
      page.getByRole("main").getByText("Одобрить КП-2026/118", { exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("main").getByRole("status").first()).toContainText(
      "Не загрузились лиды и ответы клиентам: раздел «Контакты» не ответил. Остальное показано.",
    );
    await expectNoViolations(page, "crm down");
  });
});

test.describe("Задачи: EDS не отвечает", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("директор: остальное показано, плашка называет «Документы», писем, КП и служебок нет (D26G-4: КП — тоже EDS)", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await setMock(page, "rt-pf-mock-eds-down", "1");
    await page.reload();
    const main = page.getByRole("main");
    await expect(main.getByText(/Просрочен заказ/)).toBeVisible();
    await expect(main.getByRole("status").first()).toContainText(
      "Не загрузились письма и документы: раздел «Документы» не ответил. Остальное показано.",
    );
    await expect(main.getByText(/Наложить резолюцию на письмо/)).toHaveCount(0);
    await expect(main.getByText(/Одобрить КП/)).toHaveCount(0);
    await shoot(page, "queue-partial-eds");
  });
});

test.describe("Поиск: объект, «Где посмотреть», действия", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("номер ЗВ в поиске открывает заявку, а не «Где посмотреть» (B-UIA-1)", async ({ page }) => {
    await loginAndWait(page, "universal@demo.example");
    const search = page.getByRole("combobox", { name: "Глобальный поиск" });
    await search.fill("ЗВ-2026-104");
    await page.getByRole("option", { name: /ЗВ-2026-104/ }).click();
    await expect(page).toHaveURL(
      /\/erp\/requests\?request=%D0%97%D0%92-2026-104&panel=open&tab=task/,
    );
    await expect(page.getByRole("region", { name: "Где посмотреть" })).toHaveCount(0);
    await shoot(page, "search-request");
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

  test("уведомление о договоре ведёт в карточку проекта (D2-5), «Где посмотреть» — у объектов без экрана", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/dashboard/queue");
    await page.getByRole("button", { name: "Центр уведомлений, 3 новых" }).click();
    const center = page.getByRole("dialog", { name: "Центр уведомлений" });
    await expect(center.getByRole("button", { name: /Где посмотреть/ })).toHaveCount(0);
    await center.getByRole("link", { name: /ДОГ-2026\/091/ }).click();
    await expect(page).toHaveURL(/\/eds\/projects\/.*tab=contract/);
    await expect(page.getByRole("heading", { level: 1, name: "Проект ПР-2026-097" })).toBeVisible();
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
      // шторка открывается на «Непрочитанные»; прочитанные — во «Все»
      await center.locator(".ant-segmented-item-label", { hasText: /^Все$/ }).click();
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
    const center = page.getByRole("dialog", { name: "Центр уведомлений" });
    await center.locator(".ant-segmented-item-label", { hasText: /^Все$/ }).click();
    await center.getByRole("link", { name: /Письмо ВХ-104\/26 ждёт резолюции/ }).click();
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
