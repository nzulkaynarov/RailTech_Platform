import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption } from "./support/fields";

// D17G-1 «Передача лида: делопроизводитель → менеджер» на MSW (DECISIONS 2026-11-01 п. 1, гейт D1-7 D17-G-1): у
// делопроизводителя в «Моих задачах» — «Разобрать лида», в «Ждут ответа» нет «Забрать» и поля ответа («Ответ клиенту —
// менеджер»), есть «Передать менеджеру» с запиской; клиенту ничего не уходит. Менеджер-универсал видит строку «Новый лид от
// делопроизводителя» с запиской, открывает диалог, видит «Передал(а)» и тип обращения, забирает и отвечает. Обе ширины, axe.
const WIDTHS = [1440, 390] as const;
const NOTE = "Нужен расчёт 40 т рельсов Р65 к пятнице, звонить после обеда";

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

/** Новый вход на ширине; данные моков (переписка, передачи) остаются в `localStorage` между входами. */
async function signInAt(page: Page, email: string, width: number, fresh = false): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) {
    await page.evaluate(
      fresh
        ? `window.localStorage.clear()`
        : `window.localStorage.removeItem("rt-pf-mock-session")`,
    );
  }
  await loginAndWait(page, email);
}

test.describe("D17G-1: передача лида делопроизводитель → менеджер", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`делопроизводитель разбирает и передаёт, менеджер забирает — ${String(width)}`, async ({
      page,
    }) => {
      const mobile = width < 768;
      await signInAt(page, "registrar@demo.example", width, true);

      // «Задачи»: «Разобрать лида» вместо «Взять в работу лида»
      const triage = page.getByText("Разобрать лида L-2041");
      await expect(triage).toBeVisible();
      await expect(page.getByText(/Взять в работу лида/)).toHaveCount(0);
      await shot(page, "registrar-queue");
      await expectNoViolations(page, `очередь делопроизводителя ${String(width)}`);

      // «Ждут ответа»: ни «Забрать», ни поля ответа — «Передать менеджеру»
      await spaGoto(page, "/crm/messages?lead=L-2041");
      await expect(page.getByRole("heading", { level: 2, name: "Азиз Демо" })).toBeVisible();
      await expect(page.getByRole("button", { name: /^Забрать/ })).toHaveCount(0);
      await expect(page.getByLabel("Сообщение клиенту")).toHaveCount(0);
      await expect(page.getByText(/^Ответ клиенту — менеджер\./)).toBeVisible();
      if (mobile) await page.getByRole("button", { name: "Карточка лида" }).click();
      const handOver = page.getByRole("button", { name: "Передать менеджеру: Азиз Демо" });
      await expect(handOver).toBeVisible();
      await shot(page, "registrar-dialog");
      await expectNoViolations(page, `диалог делопроизводителя ${String(width)}`);

      await handOver.click();
      const dialog = page.getByRole("dialog", { name: "Передать менеджеру" });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText(/Клиенту ничего не уйдёт/)).toBeVisible();
      await dialog.getByRole("button", { name: "Передать", exact: true }).click();
      await expect(dialog.getByText("Выберите менеджера")).toBeVisible();
      await expect(dialog.getByText(/Напишите записку/)).toBeVisible();
      await chooseOption(dialog.getByRole("combobox", { name: "Менеджер" }), "Демо Широков");
      await dialog.getByRole("textbox", { name: "Записка менеджеру" }).fill(NOTE);
      await chooseOption(
        dialog.getByRole("combobox", { name: "Тип обращения (необязательно)" }),
        "Товары",
      );
      await shot(page, "registrar-handover");
      await expectNoViolations(page, `форма передачи ${String(width)}`);
      await dialog.getByRole("button", { name: "Передать", exact: true }).click();
      await expect(
        page.getByText("Лид передан: Демо Широков. Клиенту ничего не ушло."),
      ).toBeVisible();
      await expect(dialog).toBeHidden();
      if (mobile) {
        await page.keyboard.press("Escape");
      }
      // В ленте клиенту ничего не ушло: записка — заметкой команды
      await expect(page.getByText(NOTE, { exact: true }).first()).toBeVisible();

      // Менеджер-универсал: строка «Новый лид от делопроизводителя» с запиской
      await signInAt(page, "universal@demo.example", width);
      const row = page.getByText("Новый лид от делопроизводителя L-2041");
      await expect(row).toBeVisible();
      await expect(page.getByText(/передал\(а\) Демо Канцелярова/).first()).toBeVisible();
      await shot(page, "manager-queue");
      await expectNoViolations(page, `очередь менеджера ${String(width)}`);

      await spaGoto(page, "/crm/messages?lead=L-2041");
      const note = page.getByRole("region", { name: "Записка передачи" });
      await expect(note).toBeVisible();
      await expect(note.getByText("Демо Канцелярова")).toBeVisible();
      await expect(note.getByText("Товары")).toBeVisible();
      await expect(note.getByText(new RegExp(NOTE.slice(0, 20)))).toBeVisible();
      await shot(page, "manager-dialog");
      if (mobile) await page.getByRole("button", { name: "Карточка лида" }).click();
      await page.getByRole("button", { name: "Забрать" }).last().click();
      await expect(page.getByText("Лид у вас. Бот молчит, пока вы в диалоге.")).toBeVisible();
      if (mobile && (await page.getByRole("button", { name: "Закрыть" }).count()) > 0) {
        await page.getByRole("button", { name: "Закрыть" }).last().click();
      }
      await expect(page.getByLabel("Сообщение клиенту")).toBeVisible();
      await shot(page, "manager-taken");
      await expectNoViolations(page, `менеджер забрал ${String(width)}`);
    });
  }
});
