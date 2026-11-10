import AxeBuilder from "@axe-core/playwright";
import { type Locator, type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";
import { pickFiles } from "./support/fields";

// L0-1 волны L0 «В пути / Доставлено» на MSW, 1440 и 390 px, axe WCAG 2.1 AA: проект ПР-2026-097 отгружен со склада;
// снабженец отмечает «Отправлено, в пути», затем «Доставлено» с датой, № накладной перевозчика и подтверждением доставки;
// строки поставки — «Доставлено» (клиент принимает их в кабинете), в исполнении — ссылка на файл, в журнале — запись.
// Снимки — в E2E_SCREENSHOT_DIR (docs/screens/l0-1), если он задан.
const WIDTHS = [1440, 390] as const;
const PROJECT = `/eds/projects/${encodeURIComponent("ПР-2026-097")}`;

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

test.describe("L0-1: отметки доставки клиенту в карточке проекта", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`снабженец: отгружено → в пути → доставлено, ${String(width)} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await loginAndWait(page, "supply@demo.example");
      await spaGoto(page, PROJECT);

      const card = page.locator(".ant-card", {
        has: page.getByRole("heading", { name: "Исполнение" }),
      });
      await expect(card.getByText("Отгружено").first()).toBeVisible();
      await scrollTo(card);
      await expectNoViolations(page, `исполнение: отгружено ${String(width)}`);
      await shot(page, "l0-1-shipped");

      await card.getByRole("button", { name: "Отправлено, в пути" }).click();
      const transit = page.getByRole("dialog", { name: "Отправлено клиенту, в пути" });
      await expect(transit.getByLabel("Подтверждение доставки")).toHaveCount(0);
      await transit.getByRole("button", { name: "Сохранить" }).click();
      await expect(transit).toHaveCount(0);
      await expect(card.getByText("В пути").first()).toBeVisible();
      await expect(card.getByRole("button", { name: "Отправлено, в пути" })).toHaveCount(0);

      await card.getByRole("button", { name: "Доставлено" }).click();
      const delivered = page.getByRole("dialog", { name: "Доставлено клиенту" });
      await delivered.getByLabel("№ накладной перевозчика или трек").fill("CMR-0042");
      await pickFiles(delivered.getByLabel("Подтверждение доставки"), {
        name: "pod.pdf",
        mimeType: "application/pdf",
        buffer: Buffer.from("%PDF-1.4 demo pod"),
      });
      await expect(delivered.getByText("pod.pdf")).toBeVisible();
      await expectNoViolations(page, `окно «Доставлено» ${String(width)}`);
      await shot(page, "l0-1-dialog-delivered", false);

      await delivered.getByRole("button", { name: "Сохранить" }).click();
      await expect(delivered).toHaveCount(0);
      await expect(card.getByRole("link", { name: "pod.pdf" })).toBeVisible();
      await expect(card.getByText("CMR-0042")).toBeVisible();
      await expect(card.getByRole("button", { name: "Доставлено" })).toHaveCount(0);
      const lines = card.getByRole("region", { name: "Строки поставки" });
      await expect(lines.getByText("Доставлено").first()).toBeVisible();
      await expect(page.getByText("Доставлено клиенту").first()).toBeVisible();
      await scrollTo(card);
      await expectNoViolations(page, `исполнение: доставлено ${String(width)}`);
      await shot(page, "l0-1-delivered");
    });
  }

  test("менеджер: исполнение видно, отметок нет", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, PROJECT);
    const card = page.locator(".ant-card", {
      has: page.getByRole("heading", { name: "Исполнение" }),
    });
    await expect(card.getByText("Отгружено").first()).toBeVisible();
    await expect(card.getByRole("button", { name: "Доставлено" })).toHaveCount(0);
  });
});
