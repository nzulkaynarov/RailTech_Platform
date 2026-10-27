import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// Честные заглушки и мост в старые экраны (W15-H1, UX-оценка P0-2) на MSW: раздел с мостом, раздел без аналога,
// карточка объекта из «Моей очереди», вход в старый ERP по SSO в новой вкладке; axe (WCAG 2.1 AA) на каждом экране;
// снимки 1440 и 390 для PR (`E2E_SCREENSHOT_DIR=<каталог>`).
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

async function shoot(page: Page, name: string): Promise<void> {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // Ссылка из очереди открывает боковое окно; на 390 оно Drawer поверх страницы — для снимка закрываем.
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

test.describe("Заглушки и мост", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("менеджер: из очереди — карточка лида с кнопкой «Открыть в старой CRM» и тем, что знает очередь", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    const row = page
      .getByRole("region", { name: "Что сделать сейчас" })
      .getByRole("listitem")
      .filter({ hasText: "Взять в работу лида L-2041" });
    await row.getByRole("link", { name: /Открыть/ }).click();

    await expect(page.getByRole("heading", { level: 1, name: "Лид L-2041" })).toBeVisible();
    const main = page.getByRole("main");
    await expect(main.getByText("Взять в работу лида L-2041")).toBeVisible();
    await expect(main.getByText(/ООО «Демо-Депо» · просит КП/)).toBeVisible();
    const open = main.getByRole("link", { name: /Открыть в старой CRM/ });
    await expect(open).toHaveAttribute("href", "http://crm.localhost:8088/leads/2041");
    await expect(open).toHaveAttribute("target", "_blank");
    expect(await open.getAttribute("rel")).toContain("noopener");
    await expect(main.getByText("Когда появится: в ближайшем обновлении.")).toBeVisible();
    await expect(main.getByText(/Лидов пока нет/)).toHaveCount(0);
    await shoot(page, "object-from-queue-lead");
  });

  test("директор: письмо из очереди — «Письмо ВХ-104/26», кто делает вне интерфейса, кнопки в старый экран нет", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    const row = page
      .getByRole("region", { name: "Что сделать сейчас" })
      .getByRole("listitem")
      .filter({ hasText: "Наложить резолюцию на письмо ВХ-104/26" });
    await row.getByRole("link", { name: /Открыть/ }).click();

    await expect(page.getByRole("heading", { level: 1, name: "Письмо ВХ-104/26" })).toBeVisible();
    const main = page.getByRole("main");
    await expect(main.getByText(/ООО «Демо-Депо» · заявка ЗВ-2026-104/)).toBeVisible();
    await expect(
      main.getByText(/Сейчас этой работы в интерфейсе нет; её делает директор/),
    ).toBeVisible();
    await expect(main.getByRole("link", { name: /Открыть в/ })).toHaveCount(0);
    await expect(main.getByText(/Входящих писем пока нет/)).toHaveCount(0);
    await shoot(page, "object-from-queue-letter");
  });

  test("менеджер: «Все сообщения» — мост в старую CRM; бейдж меню только с подсказкой «в старой CRM: 1»", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/messages");
    await expect(page.getByRole("heading", { level: 1, name: "Все сообщения" })).toBeVisible();
    const main = page.getByRole("main");
    await expect(
      main.getByRole("heading", { level: 2, name: "Этот раздел ещё переносится в Платформу" }),
    ).toBeVisible();
    await expect(
      main.getByText(
        "Сейчас эта работа делается в старой CRM: раздел «Входящие». Данные не потеряны.",
      ),
    ).toBeVisible();
    await expect(main.getByRole("link", { name: /Открыть в старой CRM/ })).toHaveAttribute(
      "href",
      "http://crm.localhost:8088/inbox",
    );
    await expect(main.getByText("Может попросить войти тем же логином.")).toBeVisible();
    await expect(main.getByText(/Сообщений пока нет/)).toHaveCount(0);

    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    await expect(menu.getByRole("link", { name: /Все сообщения/ })).toHaveAccessibleName(
      /в старой CRM: 1/,
    );
    await shoot(page, "stub-with-bridge");
  });

  test("директор: «Входящие» — раздела нет в старых экранах, честно «её делает директор», «Когда появится»", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/eds/inbox");
    await expect(page.getByRole("heading", { level: 1, name: "Входящие" })).toBeVisible();
    const main = page.getByRole("main");
    await expect(
      main.getByText(/Сейчас этой работы в интерфейсе нет; её делает директор/),
    ).toBeVisible();
    await expect(main.getByText("Когда появится: в ближайшем обновлении.")).toBeVisible();
    await expect(main.getByRole("link", { name: /Открыть в/ })).toHaveCount(0);
    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    await expect(menu.getByRole("link", { name: /Входящие/ })).toHaveAccessibleName("Входящие");
    await shoot(page, "stub-without-bridge");
  });

  test("снабженец: «Справочники» — мост в старый ERP; клик открывает SSO-адрес в новой вкладке", async ({
    page,
    context,
  }) => {
    await context.route("**/sso/exchange**", (route) =>
      route.fulfill({ contentType: "text/html", body: "<title>old erp</title>" }),
    );
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/catalog");
    await expect(page.getByRole("heading", { level: 1, name: "Справочники" })).toBeVisible();
    const open = page.getByRole("main").getByRole("link", { name: /Открыть в старом ERP/ });
    await expect(open).toHaveAttribute("href", "http://erp.localhost:8088/#catalog-reference");
    await expect(page.getByRole("main").getByText(/Вход выполнится сам/)).toBeVisible();
    await expectNoViolations(page, "erp bridge");

    const popup = page.waitForEvent("popup");
    await open.click();
    const tab = await popup;
    await expect
      .poll(() => tab.url(), { timeout: 10_000 })
      .toBe("http://erp.localhost:8088/sso/exchange#token=mock-one-time-token");
    expect(await tab.evaluate("window.opener")).toBeNull();
    await tab.close();
  });
});
