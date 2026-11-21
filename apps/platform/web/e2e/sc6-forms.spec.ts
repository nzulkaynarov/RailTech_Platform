import { type Page, expect, test } from "@playwright/test";

import { expectNoViolations } from "./support/axe";
import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// СЦ-6: «Создать заявку» из лида по звонку — шаг готов по тому же валидатору, согласие на «Контакте», «Осталось» на проверке,
// главная кнопка недоступна, форма не возвращает на пройденный шаг. Снимки 1440 и 390 и axe — в docs/screens/sc6-forms.

const WIDTHS = [1440, 390] as const;

async function shot(page: Page, name: string, width: number): Promise<void> {
  await waitForMotionEnd(page);
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (dir) await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

test.describe("СЦ-6: заявка по звонку", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаются спеком");

  for (const width of WIDTHS) {
    test(`форма заявки: согласие на «Контакте», «Осталось» на проверке, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, "/crm/leads?lead=L-2077&create=1&panel=open&tab=card");
      const form = page.getByRole("form", { name: "Создать заявку" });
      await expect(form).toBeVisible();

      await form.getByRole("button", { name: /^Контакт/ }).click();
      await expect(form.getByText("Клиент ещё не дал согласие.")).toBeVisible();
      await shot(page, "request-contact", width);
      await expectNoViolations(page, `контакт ${String(width)}`);

      await form.getByRole("button", { name: /^Запрос/ }).click();
      await form.getByRole("button", { name: /^Проверка и отправка/ }).click();
      const rest = form.locator(".pf-fstep-remaining");
      await expect(rest).toContainText("Без согласия клиента заявку не создать");
      await expect(rest).toContainText("записка о звонке соберётся сама, или приложите файл");
      await expect(form.getByRole("button", { name: "Создать заявку" })).toBeDisabled();
      await shot(page, "request-review", width);
      await expectNoViolations(page, `проверка ${String(width)}`);

      await rest.getByRole("button", { name: "Запрос" }).click();
      await expect(form.getByLabel("Письмо или файл запроса")).toBeVisible();
      await shot(page, "request-step-needs", width);
      await expectNoViolations(page, `запрос ${String(width)}`);
    });
  }
});
