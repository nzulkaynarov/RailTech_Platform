import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { expectNoViolations } from "./support/axe";

// ЛП-1 на MSW: в шаге «Создать заявку» из лида — вопрос «Кто это?» (Клиент / Партнёр). «Партнёр» заводит заявку кандидата,
// лид закрыт исходом «передан как партнёр» и клиентом не становится; повтор даёт ту же заявку; лид с «партнёрской» формы
// сайта начинает с «Партнёр». Снимки 1512, 1440 и 390 с axe — в docs/screens/lp1.
const WIDTHS = [1512, 1440, 390] as const;
const dir = process.env["E2E_SCREENSHOT_DIR"];

async function shot(page: Page, name: string, width: number): Promise<void> {
  await waitForMotionEnd(page);
  if (dir) await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

async function open(page: Page, width: number, lead: string): Promise<void> {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  await loginAndWait(page, "manager@demo.example");
  await spaGoto(page, `/crm/leads?lead=${lead}&create=1&panel=open&tab=card`);
}

for (const width of WIDTHS) {
  test.describe(`ЛП-1: кто это — ${String(width)}`, () => {
    test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

    test("«Партнёр»: заявка кандидата, лид закрыт исходом, повтор — та же заявка", async ({
      page,
    }) => {
      await open(page, width, "L-2041");
      const who = page.getByRole("group", { name: "Кто это?" });
      await expect(who.getByRole("radio", { name: "Клиент" })).toBeChecked();
      await shot(page, "who-client", width);
      await expectNoViolations(page, `вопрос, клиент ${String(width)}`);

      await who.getByRole("radio", { name: "Партнёр" }).check();
      const form = page.getByRole("form", { name: "Партнёр" });
      await expect(form.getByLabel("Компания")).toHaveValue("ООО Демо-Логистик");
      await expect(form.getByLabel("Что предлагает")).not.toHaveValue("");
      // без названия и без способа связи не уходит: ошибки у полей, лид не тронут
      await form.getByLabel("Компания").fill("");
      await form.getByRole("button", { name: "Передать как партнёра" }).click();
      await expect(form.getByRole("alert").first()).toBeVisible();
      await shot(page, "partner-errors", width);
      await expectNoViolations(page, `партнёр, ошибки ${String(width)}`);

      await form.getByLabel("Компания").fill("ООО Рельс-Партнёр");
      await form.getByLabel("ИНН").fill("301234567");
      await form.getByLabel("Почта").fill("partner@demo.example");
      await shot(page, "partner-form", width);
      await expectNoViolations(page, `партнёр, форма ${String(width)}`);
      await form.getByRole("button", { name: "Передать как партнёра" }).click();

      await expect(page.getByRole("status").getByText("Лид передан как партнёр")).toBeVisible();
      // ответ дан — вопрос «Кто это?» убран, остался результат
      await expect(who).toBeHidden();
      await shot(page, "partner-done", width);
      await expectNoViolations(page, `партнёр, готово ${String(width)}`);
      await page.getByRole("status").getByRole("button", { name: "Закрыть" }).click();

      // лид закрыт исходом «передан как партнёр»: не «клиент», не «отказ», из списка ушёл; повторный адрес — та же заявка
      await spaGoto(page, "/crm/leads?lead=L-2041&panel=open&tab=card");
      await expect(page.getByText("Передан как партнёр").first()).toBeVisible();
      await expect(page.getByRole("table").getByText("L-2041")).toHaveCount(0);
      await expect(page.getByText("Заявка партнёра")).toBeVisible();
      await shot(page, "partner-lead-card", width);
      await expectNoViolations(page, `карточка лида после передачи ${String(width)}`);
      await spaGoto(page, "/crm/leads?lead=L-2041&create=1&panel=open&tab=card");
      await expect(page.getByText("Лид уже был передан — это та же заявка.")).toBeVisible();
      await expect(page.getByRole("form", { name: "Партнёр" })).toBeHidden();
    });

    test("лид с «партнёрской» формы сайта начинает с «Партнёр», «Клиент» — прежняя заявка", async ({
      page,
    }) => {
      await open(page, width, "L-2044");
      const who = page.getByRole("group", { name: "Кто это?" });
      await expect(who.getByRole("radio", { name: "Партнёр" })).toBeChecked();
      await expect(page.getByRole("form", { name: "Партнёр" })).toBeVisible();
      await shot(page, "who-partner-default", width);
      await expectNoViolations(page, `по умолчанию партнёр ${String(width)}`);
      await who.getByRole("radio", { name: "Клиент" }).check();
      await expect(page.getByRole("form", { name: "Создать заявку" })).toBeVisible();
    });

    test("лид только с телефоном: без почты уходит, неверная почта — ошибка у поля", async ({
      page,
    }) => {
      await open(page, width, "L-2077");
      await page.getByRole("radio", { name: "Партнёр" }).check();
      const form = page.getByRole("form", { name: "Партнёр" });
      await expect(form.getByLabel("Телефон")).not.toHaveValue("");
      await form.getByLabel("Почта").fill("нет-собаки");
      await form.getByRole("button", { name: "Передать как партнёра" }).click();
      await expect(form.getByText("Проверьте адрес почты")).toBeVisible();
      await shot(page, "partner-phone-only", width);
      await expectNoViolations(page, `только телефон ${String(width)}`);
    });

    test("учёт не отвечает: ответ словами, введённое на месте, лид не тронут", async ({ page }) => {
      await open(page, width, "L-2041");
      await page.evaluate(`window.localStorage.setItem("rt-pf-mock-erp-down", "1")`);
      await page.getByRole("radio", { name: "Партнёр" }).check();
      const form = page.getByRole("form", { name: "Партнёр" });
      await form.getByLabel("Компания").fill("ООО Рельс-Партнёр");
      await form.getByLabel("Почта").fill("partner@demo.example");
      await form.getByRole("button", { name: "Передать как партнёра" }).click();
      await expect(form.getByRole("alert")).toContainText("Учёт не отвечает");
      await expect(form.getByLabel("Компания")).toHaveValue("ООО Рельс-Партнёр");
      await shot(page, "partner-erp-down", width);
      await expectNoViolations(page, `учёт не отвечает ${String(width)}`);
    });
  });
}
