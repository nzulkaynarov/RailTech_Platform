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

  test("менеджер: по прямой ссылке — карточка лида с кнопкой «Открыть в старой CRM» и тем, что знает очередь", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    // из очереди эта строка теперь «Где сделать»; карточка по прямой ссылке (поиск, письмо, закладка) остаётся честной
    await spaGoto(page, "/crm/leads?lead=L-2041&panel=open&tab=card");
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

  test("менеджер: «Лиды» — мост в старую CRM; бейдж меню только с подсказкой «ещё в старой системе: 2»", async ({
    page,
  }) => {
    // «Ждут ответа» — уже настоящий экран (D1-1, `e2e/crm-messages.spec.ts`); мост — на соседнем разделе.
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/leads");
    await expect(page.getByRole("heading", { level: 1, name: "Лиды" })).toBeVisible();
    const main = page.getByRole("main");
    await expect(
      main.getByRole("heading", { level: 2, name: "Этот раздел ещё переносится в Платформу" }),
    ).toBeVisible();
    await expect(
      main.getByText("Сейчас эта работа делается в старой CRM: раздел «Лиды». Данные не потеряны."),
    ).toBeVisible();
    await expect(main.getByRole("link", { name: /Открыть в старой CRM/ })).toHaveAttribute(
      "href",
      "http://crm.localhost:8088/leads",
    );
    await expect(main.getByText("Вход в старую CRM — теми же логином и паролем.")).toBeVisible();

    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    await expect(menu.getByRole("link", { name: /^Лиды/ })).toHaveAccessibleName(
      /ещё в старой системе: 2/,
    );
    // настоящий экран — живой бейдж без подсказки о старой системе
    await expect(menu.getByRole("link", { name: /Ждут ответа/ })).not.toHaveAccessibleName(
      /ещё в старой системе/,
    );
    await shoot(page, "stub-with-bridge");
  });

  test("администратор: «Обращения» — раздела нет в старых экранах, честно «её делает администратор», «Когда появится»", async ({
    page,
  }) => {
    await loginAndWait(page, "all@demo.example");
    await spaGoto(page, "/admin/tickets");
    await expect(
      page.getByRole("heading", { level: 1, name: "Обращения сотрудников" }),
    ).toBeVisible();
    const main = page.getByRole("main");
    await expect(
      main.getByText(/Сейчас этой работы в интерфейсе нет; её делает администратор/),
    ).toBeVisible();
    await expect(main.getByText("Когда появится: к пилоту.")).toBeVisible();
    await expect(main.getByRole("link", { name: /Открыть в/ })).toHaveCount(0);
    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    await expect(menu.getByRole("link", { name: /Обращения сотрудников/ })).toHaveAccessibleName(
      "Обращения сотрудников",
    );
    await shoot(page, "stub-without-bridge");
  });

  test("снабженец: «Склад» — мост в старый ERP; клик открывает SSO-адрес в новой вкладке", async ({
    page,
    context,
  }) => {
    await context.route("**/sso/exchange**", (route) =>
      route.fulfill({ contentType: "text/html", body: "<title>old erp</title>" }),
    );
    await loginAndWait(page, "supply@demo.example");
    await spaGoto(page, "/erp/stock");
    await expect(page.getByRole("heading", { level: 1, name: "Склад" })).toBeVisible();
    const open = page.getByRole("main").getByRole("link", { name: /Открыть в старом ERP/ });
    await expect(open).toHaveAttribute("href", "http://erp.localhost:8088/#my-products");
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
