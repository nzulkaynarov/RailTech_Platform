import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЗАЯВ-1 «Заявки: прошлые, черновики, по образцу» (на MSW): вкладки «В работе · Черновики · Закрытые · Все» с поиском,
// закрытая заявка открывается на просмотр, «Создать по образцу» заполняет форму сутью и файлом прежней, черновик
// продолжается и удаляется. axe 0 и снимки 1512, 1440 и 390 (`E2E_SCREENSHOT_DIR=docs/screens/req1`).
const WIDTHS = [1512, 1440, 390] as const;
const CLOSED = "ЗВ-2026-081";

async function shot(page: Page, name: string, width: number): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await page.mouse.move(0, 0);
  await waitForMotionEnd(page);
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

for (const width of WIDTHS) {
  test(`реестр: закрытые заявки, поиск и просмотр, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "universal@demo.example");
    await spaGoto(page, "/erp/requests");
    await expect(page.getByRole("heading", { level: 1, name: "Заявки" })).toBeVisible();
    await expect(page.getByText(/^Всего: \d+$/)).toBeVisible();
    await shot(page, "registry-open", width);

    await page
      .getByRole("search", { name: "Фильтры заявок" })
      .getByText("Закрытые", { exact: true })
      .click();
    await expect(page.getByText("Всего: 3", { exact: true })).toBeVisible();
    await expect(page.getByText("Закрыта", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("КП отправлено", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Стала проектом", { exact: true }).first()).toBeVisible();
    await shot(page, "registry-closed", width);
    await expectNoViolations(page, "реестр, закрытые");

    await page.getByRole("searchbox", { name: "Поиск заявок" }).fill("щебень");
    await page.getByRole("searchbox", { name: "Поиск заявок" }).press("Enter");
    await expect(page.getByText("Всего: 1", { exact: true })).toBeVisible();

    await page
      .getByRole("link", { name: `Открыть расчёт по заявке ${CLOSED}` })
      .first()
      .click();
    await expect(page).toHaveURL(new RegExp(encodeURIComponent(CLOSED)));
    await expect(
      page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${CLOSED}` }),
    ).toBeVisible();
    // только просмотр: ни «Расчёт готов», ни правки строк
    await expect(page.getByRole("button", { name: "Расчёт готов" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Создать по образцу" })).toBeVisible();
    await shot(page, "card-readonly", width);
    await expectNoViolations(page, "закрытая заявка на просмотр");
  });

  test(`по образцу: форма с сутью и файлом прежней заявки, ${String(width)} px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "universal@demo.example");
    await spaGoto(page, `/erp/calc/${encodeURIComponent(CLOSED)}`);
    await page.getByRole("link", { name: "Создать по образцу" }).click();
    await expect(page).toHaveURL(/create=1&template=/);
    await waitForMotionEnd(page);
    const form = page.getByRole("form", { name: "Создать заявку" });
    await form.getByRole("button", { name: /^Запрос/, expanded: false }).click();
    await expect(form.getByRole("textbox", { name: /Суть запроса/ })).toHaveValue(
      /Нужно 40 т щебня[\s\S]*По образцу заявки ЗВ-2026-081\./,
    );
    await expect(form.getByText("Загружено: zapros-shebyon.pdf")).toBeVisible();
    await shot(page, "by-template", width);
    await expectNoViolations(page, "форма по образцу");
  });

  test(`черновик: продолжить и удалить, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "universal@demo.example");
    await spaGoto(
      page,
      width === 390 ? "/crm/clients?create=1" : "/crm/clients?create=1&panel=open&tab=card",
    );
    const form = page.getByRole("form", { name: "Создать заявку" });
    await form.getByRole("button", { name: /^Запрос/, expanded: false }).click();
    await form
      .getByRole("textbox", { name: /Суть запроса/ })
      .fill("Нужны рельсовые накладки, 300 шт.");

    await spaGoto(page, "/erp/requests?list=drafts");
    await expect(page.getByText("Нужны рельсовые накладки, 300 шт.")).toBeVisible();
    await expect(page.getByText("Всего: 1", { exact: true })).toBeVisible();
    await shot(page, "drafts", width);
    await expectNoViolations(page, "черновики");

    await page.getByRole("button", { name: /^Удалить черновик/ }).click();
    await expect(page.getByText("Черновиков нет")).toBeVisible();
    await page.getByRole("button", { name: "Вернуть", exact: true }).click();
    await expect(page.getByText("Нужны рельсовые накладки, 300 шт.")).toBeVisible();
    await page.getByRole("link", { name: /^Продолжить черновик/ }).click();
    await expect(page).toHaveURL(/create=1/);
    await form
      .getByRole("button", { name: /^Запрос/, expanded: false })
      .click()
      .catch(() => undefined);
    await page.getByRole("button", { name: "Продолжить" }).click();
    await expect(form.getByRole("textbox", { name: /Суть запроса/ })).toHaveValue(
      "Нужны рельсовые накладки, 300 шт.",
    );
  });
}

test("без права на клиентов «По образцу» не предлагается", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginAndWait(page, "supply@demo.example");
  await spaGoto(page, "/erp/requests?list=closed");
  await expect(page.getByText("Всего: 3", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /^Создать заявку по образцу/ })).toHaveCount(0);
  await spaGoto(page, `/erp/calc/${encodeURIComponent(CLOSED)}`);
  await expect(
    page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${CLOSED}` }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Создать по образцу" })).toHaveCount(0);
});
