import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// W18A-P2-3 «Общий ящик как обращение» на MSW: вкладки со счётчиками и поиск; «Взять в работу», письмо ведёт коллега —
// «Забрать себе» с подтверждением; ответ клиента в цепочке и журнал в карточке; массовый архив с названными пропущенными;
// «Разобранные» с итогом и «Вернуть в Новые»; сотрудник без первой линии видит только своё письмо («адресовано лично»),
// отвечает и возвращает делопроизводителю. Обе ширины, axe.
const WIDTHS = [1440, 390] as const;
const REGISTRAR = "registrar@demo.example";
const UNIVERSAL = "universal@demo.example";
const MAIL_KEY = "rt-pf-mock-inbound-mail";

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

async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await page.waitForTimeout(400);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

/** Вкладка списка: на 390 полоса вкладок прокручивается, поэтому — фокус и Enter, как с клавиатуры. */
async function openTab(page: Page, name: string | RegExp): Promise<void> {
  await page.getByRole("tab", { name }).focus();
  await page.keyboard.press("Enter");
}

/** Страница не шире экрана: на 390 никакой горизонтальной прокрутки. */
async function expectFits(page: Page, context: string): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow, context).toBeLessThanOrEqual(0);
}

/** Новый вход на ширине с чистыми письмами мока. */
async function signInAt(page: Page, email: string, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) {
    await page.evaluate(
      `window.localStorage.removeItem("rt-pf-mock-session"); window.localStorage.removeItem("${MAIL_KEY}"); window.localStorage.removeItem("rt-pf-mock-imap-off")`,
    );
  }
  await loginAndWait(page, email);
}

test.describe("P2-3: общий ящик как обращение", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("вкладки, счётчики, поиск и «Все в работе» с исполнителем", async ({ page }) => {
    for (const width of WIDTHS) {
      await signInAt(page, REGISTRAR, width);
      await spaGoto(page, "/eds/mail");
      await expect(page.getByRole("heading", { level: 1, name: "Почта" })).toBeVisible();
      for (const name of [
        "Новые · 6",
        "Мои в работе · 0",
        "Все в работе · 2",
        "Разобранные · 4",
        "Подозрительные · 1",
        "Все · 12",
      ]) {
        await expect(page.getByRole("tab", { name })).toBeVisible();
      }
      const list = page.getByRole("list", { name: "Письма, ждущие разбора" });
      await expect(list.getByText("Новое · ответ в цепочке")).toBeVisible();
      await shot(page, "tabs-new");
      await expectFits(page, `список ${String(width)}`);
      await expectNoViolations(page, `новые ${String(width)}`);

      await page.getByRole("searchbox", { name: "Поиск по отправителю и теме" }).fill("акт");
      await expect(list.getByRole("listitem")).toHaveCount(1);
      await shot(page, "search");
      await page.getByRole("searchbox", { name: "Поиск по отправителю и теме" }).fill("");

      await openTab(page, "Все в работе · 2");
      const working = page.getByRole("list", { name: "Письма в работе" });
      await expect(working.getByText(/В работе у Иванов Демо с \d{2}:\d{2}/)).toBeVisible();
      await expect(working.getByText("Адресовано лично")).toBeVisible();
      await shot(page, "tab-in-work");
      await expectFits(page, `в работе ${String(width)}`);
      await expectNoViolations(page, `в работе ${String(width)}`);
    }
  });

  test("«Взять в работу» и «Забрать себе» у коллеги с подтверждением", async ({ page }) => {
    for (const width of WIDTHS) {
      await signInAt(page, REGISTRAR, width);
      await spaGoto(page, "/eds/mail/18");
      await page.getByRole("button", { name: "Взять в работу" }).click();
      // Состояние карточки, а не тост: тосты двух шагов живут вместе и совпадают по тексту.
      await expect(page.getByRole("button", { name: "Вернуть в Новые" })).toBeVisible();
      await shot(page, "card-taken");
      await expectNoViolations(page, `взято ${String(width)}`);

      await spaGoto(page, "/eds/mail/21");
      await expect(page.getByText(/Письмо уже в работе у Иванов Демо с \d{2}:\d{2}/)).toBeVisible();
      await expect(page.getByRole("link", { name: "Зарегистрировать как ВХ" })).toHaveCount(0);
      await page.getByRole("button", { name: "Забрать себе" }).click();
      await shot(page, "card-held-takeover");
      await expectNoViolations(page, `забрать себе ${String(width)}`);
      await page.getByRole("button", { name: "Забрать себе" }).first().click();
      await expect(page.getByRole("button", { name: "Вернуть в Новые" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Забрать себе" })).toHaveCount(0);
      await expectFits(page, `карточка ${String(width)}`);
    }
  });

  test("ответ клиента в цепочке: переписка по времени, журнал, «Ответить всем»", async ({
    page,
  }) => {
    for (const width of WIDTHS) {
      await signInAt(page, REGISTRAR, width);
      await spaGoto(page, "/eds/mail/22");
      const thread = page.getByRole("list", { name: "Переписка" });
      await expect(thread.getByText(/Ответ отправлен: Иванов Демо/)).toBeVisible();
      await expect(thread.getByRole("link", { name: "Скачать платёжка-118.pdf" })).toBeVisible();
      await expect(page.getByText(/клиент ответил в цепочке/)).toBeVisible();
      await shot(page, "card-thread");
      await expectFits(page, `цепочка ${String(width)}`);
      await expectNoViolations(page, `цепочка ${String(width)}`);

      await spaGoto(page, "/eds/mail/17");
      await page.getByLabel("Текст ответа").fill("Подпишем и вернём скан.");
      await expect(page.getByText(/Копия уйдёт: buh.copy@company.example/)).toBeVisible();
      await shot(page, "card-reply-all");
      await page.getByRole("button", { name: "Ответить всем" }).click();
      await expect(page.getByText("Ответ отправлен", { exact: true }).first()).toBeVisible();
      await expect(page.getByText("Разобрано", { exact: true }).first()).toBeVisible();
    }
  });

  test("массовый архив называет пропущенные; «Разобранные» с итогом и «Вернуть в Новые»", async ({
    page,
  }) => {
    for (const width of WIDTHS) {
      await signInAt(page, REGISTRAR, width);
      await spaGoto(page, "/eds/mail?tab=all");
      const list = page.getByRole("list", { name: "Все письма" });
      await list.getByRole("checkbox", { name: "Выбрать письмо «Акт сверки за октябрь»" }).check();
      await list
        .getByRole("checkbox", { name: "Выбрать письмо «Счёт на смазку для стрелок»" })
        .check();
      await list.getByRole("checkbox", { name: "Выбрать письмо «Уведомление о сверке»" }).check();
      await expect(page.getByText("Выбрано: 3")).toBeVisible();
      await shot(page, "bulk-selected");
      await page.getByRole("button", { name: "В архив" }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("button", { name: "Рассылка" }).click();
      await shot(page, "bulk-dialog");
      await expectNoViolations(page, `массовый архив ${String(width)}`);
      await dialog.getByRole("button", { name: "Отправить в архив" }).click();
      await expect(
        page.getByText("В архив: 1. Пропущено: 2 — в работе у Иванов Демо; уже разобрано."),
      ).toBeVisible();

      await openTab(page, /^Разобранные/);
      const done = page.getByRole("list", { name: "Разобранные письма" });
      await expect(done.getByRole("link", { name: "Зарегистрировано: ВХ-42/26" })).toBeVisible();
      await expect(done.getByRole("link", { name: "Лид L-2075" })).toBeVisible();
      await shot(page, "tab-done");
      await expectFits(page, `разобранные ${String(width)}`);
      await expectNoViolations(page, `разобранные ${String(width)}`);
      await done.getByRole("button", { name: "Вернуть в Новые" }).first().click();
      await expect(page.getByText("Письмо вернулось в «Новые»")).toBeVisible();
    }
  });

  test("сотрудник без первой линии: «Задачи» → своё письмо, ответ и возврат делопроизводителю", async ({
    page,
  }) => {
    for (const width of WIDTHS) {
      await signInAt(page, UNIVERSAL, width);
      await spaGoto(page, "/dashboard/queue");
      await page
        .getByRole("link", { name: /Письмо вам лично: Вопрос по гарантии/ })
        .first()
        .click();
      await expect(page).toHaveURL(/\/eds\/my-mail\/23/);
      await expect(page.getByText("Адресовано лично").first()).toBeVisible();
      await expect(
        page.getByText("Демо Широков (сотрудник), shirokov@railtech.example"),
      ).toBeVisible();
      await expect(page.getByRole("link", { name: "Зарегистрировать как ВХ" })).toHaveCount(0);
      await shot(page, "own-card");
      await expectFits(page, `своё письмо ${String(width)}`);
      await expectNoViolations(page, `своё письмо ${String(width)}`);

      await spaGoto(page, "/eds/my-mail");
      await expect(page.getByRole("tab", { name: "Мои в работе · 1" })).toBeVisible();
      await shot(page, "own-list");
      await expectNoViolations(page, `мои письма ${String(width)}`);
      await page.getByRole("link", { name: /Открыть письмо «Вопрос по гарантии/ }).click();
      await page.getByRole("button", { name: "Вернуть делопроизводителю" }).click();
      await expect(page.getByText("Письмо вернулось в «Новые»")).toBeVisible();
    }
  });

  test("администратор: правило «адресовано лично» и пометка в «Подключения · Почта · Приём»", async ({
    page,
  }) => {
    for (const width of WIDTHS) {
      await signInAt(page, "admin@demo.example", width);
      await spaGoto(page, "/admin/integrations?card=mail&panel=open");
      await expect(page.getByText("Сразу сотруднику — пометка «Адресовано лично»")).toBeVisible();
      await page.getByRole("button", { name: "Настроить приём" }).click();
      const form = page.getByRole("form", { name: "Приём почты" });
      await expect(
        form.getByRole("checkbox", { name: /Письмо сотруднику в «Кому»/ }),
      ).toBeChecked();
      await expect(form.getByLabel("Пометка у такого письма")).toHaveValue("Адресовано лично");
      await shot(page, "admin-personal-rule");
      await expectNoViolations(page, `правило лично ${String(width)}`);
      await expectFits(page, `приём ${String(width)}`);
    }
  });
});
