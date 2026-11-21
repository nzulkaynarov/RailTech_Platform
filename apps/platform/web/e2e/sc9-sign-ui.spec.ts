import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// СЦ-9: письмо на бланке, подписать некому — вместо «Подписать» подсказка и ссылка на права подписи (MSW, 1440 и 390, axe).
const WIDTHS = [1440, 390] as const;
const ID = "00000000-0000-4000-8000-000000000999";
const AT = "2026-11-01T09:00:00Z";

const STATE = {
  documents: [
    {
      id: ID,
      kind: "letter_out",
      number: null,
      status: "draft",
      version: 1,
      subject: "Ответ на требование ГНК",
      text: "Направляем пояснения.",
      ownerId: "u-demo-admin",
      amount: null,
      due_date: null,
      file_ids: [],
      erp_deal_id: null,
      recipient: { name: "ГНИ Мирабадского района", inn: null, company_id: "7", contact_id: null },
      decisions: [],
      created_at: AT,
      updated_at: AT,
      replyTo: null,
      signing: { can_sign: false, reason: "no_authority", signer_id: null },
      letter: {
        body: {
          version: 1,
          lang: "ru",
          doc: {
            type: "doc",
            content: [
              { type: "paragraph", content: [{ type: "text", text: "Направляем пояснения." }] },
            ],
          },
        },
        recipient_attention: "Начальнику ГНИ",
        recipient_email: "gni@example.uz",
        signatory_name: null,
        signatory_position: null,
        pdf: null,
        pdfPolls: 0,
        mailings: [],
        registration_requested: null,
      },
    },
  ],
  registry: [],
  files: {},
  next: { doc: 1000, memo: 100, application: 100, report: 100, outgoing: 100 },
};

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

test.describe("СЦ-9: письмо, подписать некому", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("вместо «Подписать» — подсказка и ссылка «Настройки · Права подписи»", async ({ page }) => {
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
      if (page.url().startsWith("http")) {
        await page.evaluate(`window.localStorage.removeItem("rt-pf-mock-session")`);
      }
      await loginAndWait(page, "admin@demo.example");
      await page.evaluate(
        `window.localStorage.setItem("rt-pf-mock-eds-documents", ${JSON.stringify(JSON.stringify(STATE))})`,
      );
      await spaGoto(page, `/eds/documents?scope=all&doc=${ID}&panel=open`);
      await expect(
        page.getByRole("heading", { level: 3, name: "Ответ на требование ГНК" }),
      ).toBeVisible();
      await expect(page.getByRole("button", { name: "Подписать", exact: true })).toHaveCount(0);
      const hint = page.getByText(/Подписать некому — полномочие выдаёт администратор/);
      await expect(hint).toBeVisible();
      await expect(page.getByRole("link", { name: "Настройки · Права подписи" })).toBeVisible();
      await hint.scrollIntoViewIfNeeded();
      const overflow = await page.evaluate<number>(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth",
      );
      expect(overflow, `ширина ${String(width)}`).toBeLessThanOrEqual(0);
      const dir = process.env["E2E_SCREENSHOT_DIR"];
      if (dir) {
        await page.waitForTimeout(400);
        await page.screenshot({
          path: `${dir}/letter-no-signer-${String(width)}.png`,
          fullPage: true,
        });
      }
      await expectNoViolations(page, `axe ${String(width)}`);
    }
  });
});
