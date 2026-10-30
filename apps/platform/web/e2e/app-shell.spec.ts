import { expect, test } from "@playwright/test";

import { loginAndWait, openAvatarMenu, railLinks, settledScreenshot, spaGoto } from "./support/app";
import { ROLES, ROLE_CAPTIONS, ROLE_NAMES, routesFor, visibleModules } from "./support/rbac";

// Каркас AppShell на MSW (PLT-12): панели и их память, роли по матрице, 403 по прямому URL, нижняя панель на 390.
test.describe("панели", () => {
  test.skip(({ isMobile }) => isMobile, "панели рейла и подменю — десктоп");

  test("подменю помнится, боковое окно — только по адресу; Ctrl+\\, Esc и закрепление", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    const panel = page.getByRole("complementary", { name: "Боковое окно" });
    await expect(menu).toBeVisible();
    // список: боковое окно закрыто по умолчанию (ORCHESTRATOR §3 п. 18)
    await expect(panel).toHaveCount(0);

    await page.getByRole("button", { name: "Свернуть меню" }).click();
    await expect(menu).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Меню" })).toBeVisible();
    await page.getByRole("button", { name: "Показать панель", exact: true }).click();
    await expect(panel).toBeVisible();
    await expect(page).toHaveURL(/panel=open/);
    await settledScreenshot(page, "dashboard-panel-overlay");

    // Esc при фокусе в окне закрывает его; в адресе параметра больше нет
    await panel.getByRole("tab", { selected: true }).focus();
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(page).not.toHaveURL(/panel=/);

    // перезагрузка: подменю свёрнуто (запомнено), окно закрыто (адрес без panel=open)
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Мои задачи" })).toBeVisible();
    await expect(menu).toHaveCount(0);
    await expect(panel).toHaveCount(0);

    // Ctrl+\ возвращает подменю; ссылка с ?panel=open открывает окно — поверх, рабочая область не сжимается
    await page.keyboard.press("Control+Backslash");
    await expect(menu).toBeVisible();
    await page.goto("/dashboard/queue?panel=open");
    await expect(panel).toBeVisible();
    await expect(panel).toHaveClass(/pf-panel-overlay/);
    const mainWidth = () =>
      page.evaluate<number>(
        `document.getElementById("main-content").getBoundingClientRect().width`,
      );
    const before = await mainWidth();

    // булавка: на 1440 с подменю рядом не помещается (рабочей области < 760 px) — окно остаётся поверх, выбор помнится
    const pin = page.getByRole("button", { name: "Закрепить рядом с таблицей" });
    await pin.click();
    const unpin = page.getByRole("button", { name: "Открывать поверх таблицы" });
    await expect(unpin).toHaveAttribute("aria-pressed", "true");
    await expect(panel).toHaveClass(/pf-panel-overlay/);
    expect(await mainWidth()).toBe(before);
    // подменю свёрнуто — место есть: окно в сетке рядом
    await page.keyboard.press("Control+Backslash");
    await expect(menu).toHaveCount(0);
    await expect(panel).toHaveClass(/pf-panel-docked/);
    await settledScreenshot(page, "dashboard-panel-docked");
    await page.reload();
    await expect(unpin).toBeVisible();
    await expect(panel).toHaveClass(/pf-panel-docked/);
    await unpin.click();
    await expect(panel).toHaveClass(/pf-panel-overlay/);
  });

  test("состояние панелей раздельное по пользователю", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await page.getByRole("button", { name: "Свернуть меню" }).click();
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Выйти" }).click();
    await loginAndWait(page, "manager@demo.example");
    await expect(page.getByRole("navigation", { name: "Разделы модуля" })).toBeVisible();
  });

  test("умолчания: в списках окно закрыто, на карточке объекта — открыто поверх; подменю одно на все разделы", async ({
    page,
  }) => {
    await loginAndWait(page, "all@demo.example");
    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    const panel = page.getByRole("complementary", { name: "Боковое окно" });
    const mainWidth = () =>
      page.evaluate<number>(
        `document.getElementById("main-content").getBoundingClientRect().width`,
      );

    await page.goto("/crm/leads");
    await expect(page.getByRole("heading", { level: 1, name: "Лиды" })).toBeVisible();
    await expect(menu).toBeVisible();
    await expect(panel).toHaveCount(0);
    await settledScreenshot(page, "crm-leads");
    const listWidth = await mainWidth();

    // «Мои расчёты»: подменю как в других разделах (UX-1a — своего умолчания у раздела нет); окно — по кнопке «Панель»
    await page.goto("/erp/calc");
    await expect(page.getByRole("heading", { level: 1, name: "Мои расчёты" })).toBeVisible();
    await expect(menu).toBeVisible();
    await expect(panel).toHaveCount(0);
    expect(await mainWidth()).toBe(listWidth);
    await page.getByRole("button", { name: "Показать панель", exact: true }).click();
    await expect(panel).toBeVisible();
    await expect(page.getByRole("tab", { name: "Задание" })).toBeVisible();
    await settledScreenshot(page, "erp-calc");

    // свёрнутое подменю остаётся свёрнутым при переходе в другой раздел
    await page.keyboard.press("Control+Backslash");
    await expect(menu).toHaveCount(0);
    await page.goto("/eds/inbox");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(menu).toHaveCount(0);
    await expect(panel).toHaveCount(0);
    await page.keyboard.press("Control+Backslash");
    await expect(menu).toBeVisible();

    // карточка объекта: окно открыто поверх (рабочая область не сжимается), пока его не закрыли (?panel=closed)
    await page.goto("/eds/inbox/%D0%92%D0%A5-104%2F26");
    await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-104/26" })).toBeVisible();
    await expect(panel).toBeVisible();
    await expect(panel).toHaveClass(/pf-panel-overlay/);
    await expect(panel).toHaveCSS("width", "440px");
    expect(await mainWidth()).toBe(listWidth);
    await page.getByRole("button", { name: "Скрыть панель" }).click();
    await expect(panel).toHaveCount(0);
    await expect(page).toHaveURL(/panel=closed/);
  });

  test("вкладка бокового окна живёт в ?tab= и переживает перезагрузку", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    await page.getByRole("button", { name: "Показать панель", exact: true }).click();
    await page.getByRole("tab", { name: "Уведомления" }).click();
    await expect(page).toHaveURL(/tab=notifications/);
    await page.reload();
    await expect(page.getByRole("tab", { name: "Уведомления", selected: true })).toBeVisible();
  });

  test("Ctrl+K фокусирует глобальный поиск", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    const search = page.getByRole("combobox", { name: "Глобальный поиск" });
    await page.keyboard.press("Control+k");
    await expect(search).toBeFocused();
  });

  test("активный пункт подменю и бейджи очереди", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    await expect(menu.getByRole("link", { name: /^Мои задачи/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(menu.getByRole("link", { name: "Мои задачи 3, требует действия" })).toBeVisible();
    await expect(
      menu.getByRole("link", { name: "Проекты 4, ещё в старой системе: 4" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /^Центр уведомлений, 3 новых/ })).toBeVisible();
  });

  test("главное действие без экрана — неактивная кнопка с подсказкой; с экраном — ссылка", async ({
    page,
  }) => {
    // ERP: главное действие модуля «Создать заявку» ещё без экрана — неактивна, подсказка «к пилоту»
    await loginAndWait(page, "supply@demo.example");
    await page.goto("/erp/stock");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // подменю модуля может быть свёрнуто — раскрываем
    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    if (!(await menu.isVisible())) await page.getByRole("button", { name: "Меню" }).click();
    const action = menu.getByRole("button", { name: /^Создать заявку/ });
    await expect(action).toBeDisabled();
    await expect(action).toHaveAccessibleName("Создать заявку. Появится к пилоту");
    await menu.getByText("Создать заявку").hover({ force: true });
    await expect(page.getByRole("tooltip")).toContainText("Появится к пилоту");
  });

  test("CRM: «Создать заявку» — настоящий экран (D1-2b), кнопка ведёт к лидам «Просят КП»", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await page.goto("/crm/leads");
    const action = page
      .getByRole("navigation", { name: "Разделы модуля" })
      .getByRole("link", { name: /Создать заявку/ });
    await expect(action).toHaveAttribute("href", "/crm/leads?status=wants_quote");
    await action.click();
    await expect(page.getByRole("tab", { name: "Просят КП", selected: true })).toBeVisible();
  });
});

test.describe("роли и доступ", () => {
  test.skip(({ isMobile }) => isMobile, "смена роли — десктоп");

  for (const role of ROLES) {
    test(`смена активной роли на «${ROLE_NAMES[role]}» оставляет в рейле модули матрицы; прямые URL — по матрице`, async ({
      page,
    }) => {
      await loginAndWait(page, "all@demo.example");
      await openAvatarMenu(page);
      await page.getByRole("menuitem", { name: ROLE_NAMES[role], exact: true }).click();
      // роль под аватаром сменилась
      await expect(page.getByRole("button", { name: /профиль и настройки/i })).toHaveAccessibleName(
        new RegExp(`${ROLE_CAPTIONS[role].replace(".", "\\.")}: профиль и настройки`),
      );

      const expected = visibleModules(role);
      await expect(railLinks(page)).toHaveText(expected);
      await expect(railLinks(page)).toHaveCount(expected.length);

      const { hidden, visible } = routesFor(role);
      for (const route of hidden) {
        await spaGoto(page, route);
        await expect(
          page.getByRole("heading", { level: 1, name: "Нет доступа" }),
          route,
        ).toBeVisible();
      }
      for (const route of visible) {
        await spaGoto(page, route);
        // у заглушки — заголовок раздела h2, у настоящего экрана (Входящие письма) — только h1 страницы
        await expect(page.getByRole("main").getByRole("heading").first(), route).toBeVisible();
        await expect(
          page.getByRole("heading", { level: 1, name: "Нет доступа" }),
          route,
        ).toHaveCount(0);
      }
    });
  }

  test("«Все роли» возвращает объединение ролей", async ({ page }) => {
    await loginAndWait(page, "all@demo.example");
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Менеджер", exact: true }).click();
    await expect(railLinks(page)).toHaveCount(visibleModules("MANAGER").length);
    await openAvatarMenu(page);
    await page.getByRole("menuitem", { name: "Все роли" }).click();
    await expect(railLinks(page)).toHaveCount(6);
  });

  test("у сотрудника с одной ролью выбора роли нет", async ({ page }) => {
    await loginAndWait(page, "accountant@demo.example");
    await openAvatarMenu(page);
    await expect(page.getByText("Активная роль")).toHaveCount(0);
  });

  test("модуль вне роли не рендерится в рейле; раздел вне роли — Forbidden с кнопкой «Написать администратору»", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await expect(railLinks(page)).toHaveText(visibleModules("MANAGER"));
    await expect(page.getByRole("link", { name: "Настройки" })).toHaveCount(0);

    await page.goto("/admin/roles");
    await expect(page.getByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    // W15-H7: кнопка рабочая (раньше была неактивна с подсказкой «Появится к пилоту»)
    await expect(page.getByRole("button", { name: "Написать администратору" })).toBeEnabled();
    await expect(page.getByRole("complementary", { name: "Боковое окно" })).toHaveCount(0);
    await settledScreenshot(page, "forbidden");
  });

  test("неизвестный адрес — 404 внутри каркаса", async ({ page }) => {
    await loginAndWait(page, "manager@demo.example");
    await page.goto("/crm/nothing-here");
    await expect(
      page.getByRole("heading", { level: 1, name: "Страница не найдена" }),
    ).toBeVisible();
  });
});

test.describe("узкие экраны", () => {
  // @mobile: проект mobile (Pixel 7, 390) гоняет только сценарии с этим тегом — экраны с адаптивной логикой.
  test(
    "390: рейл — нижняя панель, подменю — Drawer, боковое окно — Drawer",
    { tag: "@mobile" },
    async ({ page }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await loginAndWait(page, "director@demo.example");

      const bar = page.getByRole("navigation", { name: "Модули" });
      await expect(bar).toBeVisible();
      const box = await bar.boundingBox();
      expect(box?.y ?? 0).toBeGreaterThan(700);
      await expect(bar.getByRole("link")).toHaveCount(visibleModules("DIRECTOR").length);
      // рейл слева и подменю не занимают экран
      await expect(page.getByRole("navigation", { name: "Разделы модуля" })).toHaveCount(0);

      await page.getByRole("button", { name: "Меню" }).click();
      const drawerMenu = page.getByRole("navigation", { name: "Разделы модуля" });
      await expect(drawerMenu).toBeVisible();
      await drawerMenu.getByRole("link", { name: /^Проекты 4/ }).click();
      await expect(page).toHaveURL(/\/dashboard\/projects$/);
      await expect(drawerMenu).toBeHidden();

      await expect(page.getByRole("complementary", { name: "Боковое окно" })).toHaveCount(0);
      await page.getByRole("button", { name: "Показать панель" }).click();
      await expect(page.getByRole("tab", { name: "Карточка" })).toBeVisible();
      await expect(page).toHaveURL(/panel=open/);
      await page
        .getByRole("dialog", { name: "Боковое окно" })
        .getByRole("button", { name: "Скрыть боковое окно" })
        .click();
      await expect(page.getByRole("tab", { name: "Карточка" })).toBeHidden();

      const scrollWidth = await page.evaluate("document.documentElement.scrollWidth");
      expect(scrollWidth).toBeLessThanOrEqual(390);
    },
  );

  test("1100: боковое окно — Drawer поверх основного, по умолчанию закрыт", async ({ page }) => {
    test.skip(test.info().project.name === "mobile");
    await page.setViewportSize({ width: 1100, height: 800 });
    await loginAndWait(page, "director@demo.example");
    await expect(page.getByRole("tab", { name: "Сегодня" })).toBeHidden();
    await page.getByRole("button", { name: "Показать панель", exact: true }).click();
    await expect(page.getByRole("tab", { name: "Сегодня" })).toBeVisible();
  });

  test("1280 и 1440: нет горизонтальной прокрутки страницы", async ({ page }) => {
    test.skip(test.info().project.name === "mobile");
    await loginAndWait(page, "all@demo.example");
    for (const width of [1440, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      for (const route of [
        "/dashboard/queue",
        "/eds/inbox",
        "/chats?scope=internal",
        "/erp/calc",
      ]) {
        await spaGoto(page, route);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        const scrollWidth = await page.evaluate("document.documentElement.scrollWidth");
        expect(scrollWidth, `${String(width)} ${route}`).toBeLessThanOrEqual(width);
      }
    }
  });
});
