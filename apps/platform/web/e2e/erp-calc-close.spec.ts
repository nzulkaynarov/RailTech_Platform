import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЛХ-2 «Закрыть заявку на любом шаге» (на MSW): кнопка в шапке карточки заявки, причина из справочника, комментарий у
// «Другое», подтверждение; КП уже у клиента — «Ошибка», «Дубль» и «Тест» недоступны. axe 0 и снимки 1512, 1440 и 390 для PR
// (`E2E_SCREENSHOT_DIR=docs/screens/lh2`).
const WIDTHS = [1512, 1440, 390] as const;
const OPEN = "ЗВ-2026-101"; // КП клиенту не уходило
const DRAFT = "ЗВ-2026-120"; // черновик из передачи лида: задания расчёта нет
const SENT = "ЗВ-2026-109"; // КП отклонено клиентом: уже было у клиента

async function shot(page: Page, name: string, width: number): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await page.mouse.move(0, 0);
  await waitForMotionEnd(page);
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

async function openCalc(page: Page, number: string): Promise<void> {
  await spaGoto(page, `/erp/calc/${encodeURIComponent(number)}`);
  await expect(
    page.getByRole("heading", { level: 1, name: `Расчёт по заявке ${number}` }),
  ).toBeVisible();
}

for (const width of WIDTHS) {
  test(`закрыть заявку до отправки КП, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "supply@demo.example");
    await openCalc(page, OPEN);
    await shot(page, "card", width);

    await page.getByRole("button", { name: "Закрыть заявку" }).click();
    const dialog = page.getByRole("dialog", { name: `Закрыть заявку ${OPEN}` });
    await expect(dialog.getByRole("radio", { name: "Оформлена по ошибке" })).toBeEnabled();
    const confirm = dialog.getByRole("button", { name: "Закрыть заявку" });
    await expect(confirm).toBeDisabled();
    await dialog.getByRole("radio", { name: "Другое — комментарий" }).check();
    await expect(confirm).toBeDisabled(); // «Другое» без комментария не закрывается
    await shot(page, "dialog", width);
    await expectNoViolations(page, "окно «Закрыть заявку»");
    await dialog.getByRole("textbox", { name: "Комментарий" }).fill("Передали другому подрядчику");
    await expect(confirm).toBeEnabled();
    await confirm.click();

    await expect(
      page.getByText("Заявка закрыта: Другое — комментарий", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Передали другому подрядчику")).toBeVisible();
    await expect(page.getByRole("button", { name: "Закрыть заявку" })).toHaveCount(0);
    await shot(page, "closed", width);
    await expectNoViolations(page, "заявка закрыта");

    // из очереди «Заявки в расчёте» ушла
    await spaGoto(page, "/erp/requests");
    await expect(page.getByRole("heading", { level: 1, name: "Заявки" })).toBeVisible();
    await expect(page.getByRole("link", { name: new RegExp(OPEN) })).toHaveCount(0);
  });

  test(`КП уже у клиента: только причины клиента, ${String(width)} px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "universal@demo.example");
    await openCalc(page, SENT);
    await page.getByRole("button", { name: "Закрыть заявку" }).first().click();
    const dialog = page.getByRole("dialog", { name: `Закрыть заявку ${SENT}` });
    await expect(dialog.getByText(/КП уже у клиента/)).toBeVisible();
    for (const name of ["Оформлена по ошибке", "Дубль", "Тест"]) {
      await expect(dialog.getByRole("radio", { name })).toBeDisabled();
    }
    await expect(dialog.getByRole("radio", { name: "Клиент не отвечает" })).toBeEnabled();
    await shot(page, "quote-sent", width);
    await expectNoViolations(page, "КП у клиента");
    await dialog.getByRole("radio", { name: "Клиент не отвечает" }).check();
    await dialog.getByRole("button", { name: "Закрыть заявку" }).click();
    await expect(
      page.getByText("Заявка закрыта: Клиент не отвечает", { exact: true }),
    ).toBeVisible();
  });

  test(`черновик без расчёта: карточка заявки и «Закрыть заявку», ${String(width)} px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await loginAndWait(page, "universal@demo.example");
    await spaGoto(page, `/erp/calc/${encodeURIComponent(DRAFT)}`);
    await expect(page.getByText(/Клиент просит цену на 40 т щебня/)).toBeVisible();
    await expect(page.getByText(/Расчёта по заявке пока нет/)).toBeVisible();
    await shot(page, "draft-card", width);
    await expectNoViolations(page, "карточка черновика заявки");
    await page.getByRole("button", { name: "Закрыть заявку" }).click();
    const dialog = page.getByRole("dialog", { name: `Закрыть заявку ${DRAFT}` });
    await dialog.getByRole("radio", { name: "Оформлена по ошибке" }).check();
    await shot(page, "draft-dialog", width);
    await dialog.getByRole("button", { name: "Закрыть заявку" }).click();
    await expect(page.getByText("Заявка закрыта: Оформлена по ошибке")).toBeVisible();
    await expect(page.getByRole("button", { name: "Закрыть заявку" })).toHaveCount(0);
    await shot(page, "draft-closed", width);
    await expectNoViolations(page, "черновик закрыт");
  });
}

test("окно «Задание» списка заявок: «Закрыть заявку» и у заявки с расчётом, и у черновика", async ({
  page,
  isMobile,
}) => {
  test.skip(isMobile, "боковое окно списка — на десктопе");
  await loginAndWait(page, "universal@demo.example");
  const panel = page.locator("#pf-context-panel");

  await spaGoto(page, `/erp/requests?request=${encodeURIComponent(OPEN)}&panel=open&tab=task`);
  await expect(panel.getByRole("heading", { name: OPEN })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Закрыть заявку" })).toBeVisible();

  await spaGoto(page, `/erp/requests?request=${encodeURIComponent(DRAFT)}&panel=open&tab=task`);
  await expect(panel.getByText(/Клиент просит цену на 40 т щебня/)).toBeVisible();
  await expect(panel.getByRole("button", { name: "Закрыть заявку" })).toBeVisible();
  await expectNoViolations(page, "окно «Задание» черновика");
});
