import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// СЦ-6: заявка по звонку без поиска файла — записка о звонке собирается сама для лида со звонком (когда согласие есть) и по
// кнопке «Основание — звонок» без лида; нет бланка — причина и «приложите файл». Снимки 1440 и 390 и axe — в
// docs/screens/sc6-callnote.

const WIDTHS = [1440, 390] as const;

async function shot(page: Page, name: string, width: number): Promise<void> {
  await waitForMotionEnd(page);
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

async function setMock(page: Page, key: string, value: string): Promise<void> {
  await page.evaluate(
    `window.localStorage.setItem(${JSON.stringify(key)}, ${JSON.stringify(value)})`,
  );
}

test.describe("СЦ-6: записка о звонке", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаются спеком");

  for (const width of WIDTHS) {
    test(`лид со звонка: согласие на «Контакте» → записка приложена сама → заявка, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/leads?lead=L-2077&create=1&panel=open&tab=card");
      const form = page.getByRole("form", { name: "Создать заявку" });
      await expect(form).toBeVisible();

      await form.getByRole("button", { name: /^Контакт/ }).click();
      await form.getByRole("checkbox", { name: "Согласие получено" }).check();
      await form.getByRole("button", { name: /^Запрос/ }).click();
      await expect(form.getByText("Записка о звонке приложена")).toBeVisible();
      await expect(form.getByRole("button", { name: /^Открыть/ })).toBeVisible();
      await expect(form.getByText("Заменить файлом")).toBeVisible();
      await shot(page, "call-note-lead", width);
      await expectNoViolations(page, `записка у лида ${String(width)}`);

      await form.getByRole("button", { name: /^Проверка и отправка/ }).click();
      const submit = form.getByRole("button", { name: "Создать заявку" });
      await expect(submit).toBeEnabled();
      await submit.click();
      await expect(page.getByText("Заявка создана")).toBeVisible();
    });

    test(`без лида: «Основание — звонок» собирает записку по полям формы, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/clients?client=3&create=1&panel=open&tab=card");
      const form = page.getByRole("form", { name: "Создать заявку" });
      await expect(form).toBeVisible();
      await expect(form.getByText(/^Бобур Снабженцев/)).toBeVisible();

      await form.getByRole("button", { name: /^Запрос/ }).click();
      await form.getByLabel("Суть запроса").fill("Повторный заказ накладок");
      await shot(page, "call-note-button", width);
      await expectNoViolations(page, `кнопка основания ${String(width)}`);
      await form.getByRole("button", { name: "Основание — звонок" }).click();
      await expect(form.getByText("Записка о звонке приложена")).toBeVisible();
      await shot(page, "call-note-no-lead", width);
      await expectNoViolations(page, `записка без лида ${String(width)}`);
    });

    test(`нет бланка: причина и «приложите файл», ${String(width)} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await setMock(page, "rt-pf-mock-no-letterhead", "1");
      await spaGoto(page, "/crm/clients?client=3&create=1&panel=open&tab=card");
      const form = page.getByRole("form", { name: "Создать заявку" });
      await expect(form.getByText(/^Бобур Снабженцев/)).toBeVisible();
      await form.getByRole("button", { name: /^Запрос/ }).click();
      await form.getByLabel("Суть запроса").fill("Повторный заказ накладок");
      await form.getByRole("button", { name: "Основание — звонок" }).click();
      await expect(
        form.getByText(
          "Записку о звонке не собрать: в компании не настроен бланк. Приложите файл.",
        ),
      ).toBeVisible();
      await shot(page, "call-note-no-letterhead", width);
      await expectNoViolations(page, `нет бланка ${String(width)}`);
    });
  }
});
