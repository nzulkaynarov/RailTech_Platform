import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";

// MAIL-NOW на MSW: делопроизводитель нажимает «Проверить почту» — ящик опрашивается сразу, новое письмо появляется в
// списке без перезагрузки; видно, когда была последняя проверка и сколько пришло; повтор раньше 20 секунд не
// опрашивает ящик, а подсказывает паузу. Обе ширины, axe (WCAG 2.1 AA), снимки в docs/screens/MAIL-NOW/.
// Данные вымышленные.
const WIDTHS = [1440, 390] as const;
const REGISTRAR = "registrar@demo.example";
const KEYS = [
  "rt-pf-mock-session",
  "rt-pf-mock-inbound-mail",
  "rt-pf-mock-imap-off",
  "rt-pf-mock-mail-check",
];
const NEW_LETTER = "Срочно: подтвердите наличие шпал на этой неделе";

async function settledShot(page: Page, name: string): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await page.waitForTimeout(500);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

async function expectFits(page: Page, context: string): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow, context).toBeLessThanOrEqual(0);
}

async function signInAt(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) {
    await page.evaluate(KEYS.map((key) => `window.localStorage.removeItem("${key}");`).join(" "));
  }
  await loginAndWait(page, REGISTRAR);
}

for (const width of WIDTHS) {
  test(`@mobile «Проверить почту»: письмо появляется сразу, повтор — пауза · ${String(width)}`, async ({
    page,
  }) => {
    await signInAt(page, width);
    await spaGoto(page, "/eds/mail");
    await expect(page.getByRole("heading", { level: 1, name: "Почта" })).toBeVisible();
    const list = page.getByRole("list", { name: "Письма, ждущие разбора" });
    await expect(list).toBeVisible();
    await expect(page.getByText("Проверено 2 мин назад")).toBeVisible();
    const button = page.getByRole("button", { name: "Проверить почту" });
    await expect(button).toBeVisible();
    // Подпись видна на широком экране; на узком у кнопки остаётся иконка, имя — для экранного диктора.
    const caption = button.locator(".pf-mail-check-text");
    if (width >= 768) await expect(caption).toBeVisible();
    else await expect(caption).toBeHidden();
    await expect(list.getByText(NEW_LETTER)).toHaveCount(0);
    await expectNoViolations(page, "список с кнопкой «Проверить почту»");
    await expectFits(page, "список с кнопкой");
    await settledShot(page, "mail-check-start");

    await button.click();
    await expect(page.getByRole("button", { name: "Проверяю…" })).toBeDisabled();
    await settledShot(page, "mail-check-busy");

    const result = page.getByRole("status", { name: "Итог проверки почты" });
    await expect(result).toHaveText("Новых писем: 1");
    await expect(list.getByText(NEW_LETTER)).toBeVisible();
    await expect(page.getByText("Проверено только что")).toBeVisible();
    await expectNoViolations(page, "после проверки");
    await expectFits(page, "после проверки");
    await settledShot(page, "mail-check-found");

    // Повтор сразу: ящик второй раз не опрашивается.
    await page.getByRole("button", { name: "Проверить почту" }).click();
    await expect(result).toHaveText(/^Можно проверить ещё раз через \d+ с$/);
    await expect(list.getByText(NEW_LETTER)).toHaveCount(1);
    await expectNoViolations(page, "пауза между проверками");
    await settledShot(page, "mail-check-wait");
  });

  test(`«Проверить почту»: сервер недоступен и почта не настроена · ${String(width)}`, async ({
    page,
  }) => {
    await signInAt(page, width);
    await page.evaluate(`window.localStorage.setItem("rt-pf-mock-mail-check", "error")`);
    await spaGoto(page, "/eds/mail");
    await expect(page.getByRole("list", { name: "Письма, ждущие разбора" })).toBeVisible();
    await page.getByRole("button", { name: "Проверить почту" }).click();
    const result = page.getByRole("status", { name: "Итог проверки почты" });
    await expect(result).toHaveText("Не удалось подключиться к почтовому серверу");
    await expectNoViolations(page, "ошибка проверки");
    await settledShot(page, "mail-check-error");

    await page.evaluate(`window.localStorage.setItem("rt-pf-mock-imap-off", "1")`);
    await page.reload();
    await expect(page.getByRole("heading", { name: "Почта не подключена" })).toBeVisible();
    await page.getByRole("button", { name: "Проверить почту" }).click();
    await expect(page.getByRole("status", { name: "Итог проверки почты" })).toHaveText(
      "Почта не настроена — Настройки · Почта",
    );
    await expectNoViolations(page, "почта не настроена");
  });
}
