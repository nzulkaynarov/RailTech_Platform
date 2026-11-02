import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// W18A-P2 «Входящая почта» на MSW: письмо общего ящика в «Моих задачах» и очереди делопроизводителя; «Подсказать» — только
// по кнопке, ничего не делает сама; одним подтверждением письмо становится ВХ (форма P8 с вложением), лидом или уходит в
// архив и пропадает из очереди; без IMAP — подсказка «Настройки · Подключения · Почта»; у менеджера очереди нет; приём в
// «Подключениях». Обе ширины, axe.
const WIDTHS = [1440, 390] as const;
const REGISTRAR = "registrar@demo.example";
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

test.describe("P2: входящая почта общего ящика", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("очередь в «Моих задачах», карточка письма, «Подсказать» и «Создать лид»", async ({
    page,
  }) => {
    for (const width of WIDTHS) {
      await signInAt(page, REGISTRAR, width);
      await spaGoto(page, "/dashboard/queue");
      const row = page.getByRole("link", { name: /Разобрать письмо: Акт сверки за октябрь/ });
      await expect(row.first()).toBeVisible();
      await shot(page, "queue");

      await spaGoto(page, "/eds/mail");
      await expect(page.getByRole("heading", { level: 1, name: "Входящая почта" })).toBeVisible();
      const list = page.getByRole("list", { name: "Письма, ждущие разбора" });
      await expect(list.getByRole("listitem")).toHaveCount(4);
      await shot(page, "mail-list");
      await expectNoViolations(page, `список ${String(width)}`);

      await spaGoto(page, "/eds/mail/18");
      await expect(
        page.getByRole("heading", { level: 1, name: "Запрос КП на стрелочные переводы" }),
      ).toBeVisible();
      await expect(page.getByText("Покупатель", { exact: true })).toHaveCount(0);
      await page.getByRole("button", { name: "Подсказать" }).click();
      await expect(page.getByText("Предлагает: Создать лид")).toBeVisible();
      await expect(page.getByText("Новое", { exact: true }).first()).toBeVisible();
      await shot(page, "mail-card-assist");
      await expectNoViolations(page, `карточка ${String(width)}`);

      await page.getByRole("button", { name: "Создать лид" }).click();
      await expect(page.getByRole("group", { name: "Что произойдёт" })).toBeVisible();
      await page.getByRole("button", { name: "Создать лид" }).last().click();
      await expect(page.getByText(/Лид L-2068 создан/)).toBeVisible();
      await expect(list.getByRole("listitem")).toHaveCount(3);
    }
  });

  test("«Зарегистрировать входящее» из письма: форма P8 с вложением, письмо уходит из очереди", async ({
    page,
  }) => {
    for (const width of WIDTHS) {
      await signInAt(page, REGISTRAR, width);
      await spaGoto(page, "/eds/mail/17");
      await expect(page.getByText("Предлагает: Зарегистрировать входящее")).toBeVisible();
      await page.getByRole("link", { name: "Зарегистрировать входящее" }).click();
      await expect(
        page.getByText("Из письма: «Акт сверки за октябрь» от ООО «Демо-Поставка»"),
      ).toBeVisible();
      await expect(page.getByText("акт-сверки-октябрь.pdf")).toBeVisible();
      await shot(page, "register-from-mail");
      await expectNoViolations(page, `форма ${String(width)}`);
      await page.getByRole("button", { name: "Зарегистрировать", exact: true }).click();
      await expect(
        page.getByText(/Входящее ВХ-.* зарегистрировано|зарегистрировано/i).first(),
      ).toBeVisible();
      await spaGoto(page, "/eds/mail");
      await expect(
        page.getByRole("list", { name: "Письма, ждущие разбора" }).getByRole("listitem"),
      ).toHaveCount(3);
    }
  });

  test("без настроенного приёма — подсказка, где подключить; у менеджера очереди нет", async ({
    page,
  }) => {
    for (const width of WIDTHS) {
      await signInAt(page, REGISTRAR, width);
      await page.evaluate(`window.localStorage.setItem("rt-pf-mock-imap-off", "1")`);
      await spaGoto(page, "/eds/mail");
      await expect(page.getByRole("heading", { name: "Почта не подключена" })).toBeVisible();
      await shot(page, "mail-off");
      await expectNoViolations(page, `без IMAP ${String(width)}`);

      await signInAt(page, "universal@demo.example", width);
      await spaGoto(page, "/dashboard/queue");
      await expect(page.getByRole("link", { name: /Разобрать письмо/ })).toHaveCount(0);
    }
  });

  test("администратор: приём в карточке «Почта», «Проверить приём»", async ({ page }) => {
    for (const width of WIDTHS) {
      await signInAt(page, "admin@demo.example", width);
      await spaGoto(page, "/admin/integrations?card=mail&panel=open");
      await expect(page.getByRole("heading", { name: "Приём: общий ящик (IMAP)" })).toBeVisible();
      await page.getByRole("button", { name: "Проверить приём" }).click();
      await expect(page.getByText("Ящик открывается: писем в папке — 128")).toBeVisible();
      await shot(page, "admin-imap");
      await expectNoViolations(page, `приём ${String(width)}`);
    }
  });
});
