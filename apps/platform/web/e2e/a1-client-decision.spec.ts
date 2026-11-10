import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { chooseOption, pickFiles } from "./support/fields";

// A1 и A2 волны 18a «Отметить за контрагента» на MSW, 1440 и 390 px, axe WCAG 2.1 AA:
// — отправленное КП ждёт решения клиента; клиент ответил письмом — менеджер записывает «Клиент принял» с каналом, лицом,
//   датой, комментарием и обязательным подтверждением клиента; в карточке — «Отмечено сотрудником» и файл;
// — «Согласован клиентом» у договора — с каналом и лицом, значок в истории договора.
// Снимки — в E2E_SCREENSHOT_DIR (docs/screens/a1), если он задан.
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

async function shot(page: Page, name: string, fullPage = true): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await expect(page.locator(".ant-message-notice")).toHaveCount(0, { timeout: 15_000 });
  await waitForMotionEnd(page);
  await page.waitForTimeout(400);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage });
}

async function scrollTo(target: Locator): Promise<void> {
  await expect(async () => {
    await target.scrollIntoViewIfNeeded({ timeout: 2000 });
  }).toPass({ timeout: 10_000 });
}

const SENT_QUOTE = `/eds/drafts/${encodeURIComponent("КП-2026/113")}`;

test.describe("A1: решение клиента по КП по его подтверждению", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`менеджер: «Клиент принял» с подтверждением клиента, ${String(width)} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "manager@demo.example");
      await spaGoto(page, SENT_QUOTE);

      const card = page.locator(".ant-card", {
        has: page.getByRole("heading", { name: "Решение клиента" }),
      });
      await expect(card.getByText("Ждёт решения клиента.")).toBeVisible();
      await scrollTo(card);
      await expectNoViolations(page, `КП ждёт решения ${String(width)}`);
      await shot(page, "a1-quote-awaiting");

      await card.getByRole("button", { name: "Клиент принял" }).click();
      const dialog = page.getByRole("dialog", { name: "Клиент принял КП" });
      await expect(dialog).toBeVisible();
      // без подтверждения клиента не записывается
      await dialog.getByRole("button", { name: "Записать" }).click();
      await expect(
        dialog.getByText("Приложите подтверждение клиента", { exact: true }),
      ).toBeVisible();

      await chooseOption(dialog.getByLabel("Как клиент сообщил"), "почта");
      await dialog.getByLabel("Кто со стороны клиента").fill("Каримов А., снабженец");
      await dialog.getByLabel("Что ответил клиент").fill("Согласны с КП, ждём договор");
      await pickFiles(dialog.getByLabel("Подтверждение клиента"), {
        name: "letter.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("%PDF-1.4 demo letter"),
      });
      await expect(dialog.getByText("letter.pdf")).toBeVisible();
      await expectNoViolations(page, `окно «Клиент принял» ${String(width)}`);
      await shot(page, "a1-dialog-accept", false);

      await dialog.getByRole("button", { name: "Записать" }).click();
      await expect(dialog).toHaveCount(0);
      await expect(card.getByText(/^Клиент принял КП\./)).toBeVisible();
      await expect(card.getByText("Отмечено сотрудником")).toBeVisible();
      await expect(card.getByText(/почта · подтвердил: Каримов А., снабженец/)).toBeVisible();
      await expect(card.getByRole("link", { name: "Подтверждение: letter.pdf" })).toBeVisible();
      await expect(card.getByRole("button", { name: "Клиент принял" })).toHaveCount(0);
      await scrollTo(card);
      await expectNoViolations(page, `КП принято по подтверждению ${String(width)}`);
      await shot(page, "a1-quote-accepted");
    });
  }
});

test.describe("A2: «Согласован клиентом» с каналом и лицом", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`бухгалтер: согласие клиента с договором, ${String(width)} px`, async ({ page }) => {
      // Проект договора — сформирован и отправлен клиенту в боковом окне (на телефоне лист закрывается после действия).
      await page.setViewportSize({ width: 1440, height: 900 });
      await loginAndWait(page, "accountant@demo.example");
      const project = `/eds/projects/${encodeURIComponent("ПР-2026-104")}`;
      await spaGoto(page, `${project}?panel=open&tab=contract`);
      const side = page.locator("#pf-context-panel");
      await side.getByRole("button", { name: "Сформировать проект договора" }).click();
      await side.getByRole("button", { name: "На согласование клиенту" }).click();

      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      if (width === 390) await spaGoto(page, `${project}?sheet=contract`);
      const panel = width === 390 ? page.getByRole("dialog") : side;

      await chooseOption(panel.getByLabel("Как клиент сообщил"), "бумага");
      await panel.getByLabel("Кто со стороны клиента").fill("Юсупова Н., юрист");
      await expectNoViolations(page, `договор: согласие клиента ${String(width)}`);
      await shot(page, "a2-contract-agree");

      await panel.getByRole("button", { name: "Отметить: согласован клиентом" }).click();
      // На телефоне лист закрывается после действия: запись видна в журнале документов карточки.
      const history =
        width === 390
          ? page.getByRole("list", { name: "Журнал документов" })
          : side.getByRole("list", { name: "История договора" });
      await expect(history.getByText("Отмечено сотрудником")).toBeVisible();
      await expect(history.getByText(/бумага · подтвердил: Юсупова Н., юрист/)).toBeVisible();
      await scrollTo(history);
      await expectNoViolations(page, `договор: история ${String(width)}`);
      await shot(page, "a2-contract-history");
    });
  }
});
