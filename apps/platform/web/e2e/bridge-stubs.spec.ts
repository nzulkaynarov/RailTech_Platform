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

  test("по прямой ссылке — карточка объекта без экрана с кнопкой «Открыть в старом ERP»", async ({
    page,
  }) => {
    await loginAndWait(page, "all@demo.example");
    // «Лиды» — настоящий экран (D1-2b); заглушка-карточка остаётся у разделов без экрана (счета и оплаты)
    await spaGoto(page, "/eds/payments/%D0%A1%D0%A7-2026%2F142?panel=open&tab=payment");
    await expect(page.getByRole("heading", { level: 1, name: "Счёт СЧ-2026/142" })).toBeVisible();
    const main = page.getByRole("main");
    const open = main.getByRole("link", { name: /Открыть в старом ERP/ });
    await expect(open).toHaveAttribute("href", "http://erp.localhost:8088/#payments");
    await expect(open).toHaveAttribute("target", "_blank");
    expect(await open.getAttribute("rel")).toContain("noopener");
    await expect(main.getByText("Когда появится: к пилоту.")).toBeVisible();
    await shoot(page, "object-from-queue-invoice");
  });

  test("менеджер: прямая ссылка на лида открывает новый экран «Лиды» с карточкой (D1-2b)", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/leads?lead=L-2041&panel=open&tab=card");
    await expect(page.getByRole("heading", { level: 1, name: "Лиды" })).toBeVisible();
    await expect(
      page.locator("#pf-context-panel").getByRole("heading", { name: "Азиз Демо" }),
    ).toBeVisible();
    await expect(
      page.getByRole("main").getByRole("link", { name: /Открыть в старой CRM/ }),
    ).toHaveCount(0);
  });

  test("директор: «Проекты» — мост в старый ERP; бейдж меню только с подсказкой «ещё в старой системе: 4»", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    await spaGoto(page, "/dashboard/projects");
    await expect(page.getByRole("heading", { level: 1, name: "Проекты" })).toBeVisible();
    const main = page.getByRole("main");
    await expect(
      main.getByRole("heading", { level: 2, name: "Этот раздел ещё переносится в Платформу" }),
    ).toBeVisible();
    await expect(
      main.getByText(
        "Сейчас эта работа делается в старом ERP: раздел «Сделки». Данные не потеряны.",
      ),
    ).toBeVisible();
    await expect(main.getByRole("link", { name: /Открыть в старом ERP/ })).toHaveAttribute(
      "href",
      "http://erp.localhost:8088/#crm-deals",
    );

    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    await expect(menu.getByRole("link", { name: /^Проекты/ })).toHaveAccessibleName(
      /ещё в старой системе: 4/,
    );
    // настоящий экран — живой бейдж без подсказки о старой системе
    await expect(menu.getByRole("link", { name: /Мои задачи/ })).not.toHaveAccessibleName(
      /ещё в старой системе/,
    );
    await shoot(page, "stub-with-bridge");
  });

  test("«Чаты · Команда» — раздела нет в старых экранах, честно «её делает команда», «Когда появится»", async ({
    page,
  }) => {
    await loginAndWait(page, "all@demo.example");
    await spaGoto(page, "/chats?scope=internal");
    await expect(page.getByRole("heading", { level: 1, name: "Команда" })).toBeVisible();
    const main = page.getByRole("main");
    await expect(
      main.getByText(/Сейчас этой работы в интерфейсе нет; её делает команда/),
    ).toBeVisible();
    await expect(main.getByText("Когда появится: к пилоту.")).toBeVisible();
    await expect(main.getByRole("link", { name: /Открыть в/ })).toHaveCount(0);
    const menu = page.getByRole("navigation", { name: "Разделы модуля" });
    await expect(menu.getByRole("link", { name: /^Команда/ })).toHaveAccessibleName("Команда");
    await shoot(page, "stub-without-bridge");
  });

  test("«Чаты · С клиентами» (B-D18-1): менеджеру с разделом лидов — «Входящие» старой CRM", async ({
    page,
  }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/chats?scope=external");
    await expect(page.getByRole("heading", { level: 1, name: "С клиентами" })).toBeVisible();
    await expect(
      page.getByRole("main").getByRole("link", { name: /Открыть в старой CRM/ }),
    ).toHaveAttribute("href", "http://crm.localhost:8088/inbox");
    await shoot(page, "stub-chats-external-manager");
  });

  test("«Чаты · С клиентами» (B-D18-1): бухгалтеру без реестра лидов — кто делает, без кнопки в старую CRM", async ({
    page,
  }) => {
    await loginAndWait(page, "accountant@demo.example");
    await spaGoto(page, "/chats?scope=external");
    await expect(page.getByRole("heading", { level: 1, name: "С клиентами" })).toBeVisible();
    const main = page.getByRole("main");
    await expect(
      main.getByText(
        "Сейчас этой работы в интерфейсе нет; её делает менеджер клиента: попросите его переслать нужное сообщение или файл.",
      ),
    ).toBeVisible();
    await expect(main.getByRole("link", { name: /Открыть в/ })).toHaveCount(0);
    // Реестра лидов у бухгалтера нет: «Ждут ответа» и «Лиды» в меню не показываются.
    await expect(page.getByRole("link", { name: /Ждут ответа|^Лиды/ })).toHaveCount(0);
    await shoot(page, "stub-chats-external-accountant");
  });

  test("«Платежи» — мост в старый ERP; клик открывает SSO-адрес в новой вкладке", async ({
    page,
    context,
  }) => {
    await context.route("**/sso/exchange**", (route) =>
      route.fulfill({ contentType: "text/html", body: "<title>old erp</title>" }),
    );
    await loginAndWait(page, "all@demo.example");
    await spaGoto(page, "/eds/payments");
    await expect(page.getByRole("heading", { level: 1, name: "Счета и оплаты" })).toBeVisible();
    const open = page.getByRole("main").getByRole("link", { name: /Открыть в старом ERP/ });
    await expect(open).toHaveAttribute("href", "http://erp.localhost:8088/#payments");
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
