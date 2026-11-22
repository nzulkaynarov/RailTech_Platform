import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// ГЛ-0: письмо «На подписи» без тупика — у кого письмо, «Подписать самому», отказ строгого режима целым предложением,
// «Напомнить / Отозвать / Сменить подписанта» (MSW, 1440 и 390, axe).
const WIDTHS = [1440, 390] as const;
const ID = "00000000-0000-4000-8000-000000000999";
const AT = "2026-11-01T09:00:00Z";

const DIRECTOR = {
  can_sign: false,
  reason: "author_cannot_sign",
  signer_id: "u-demo-director",
  signer_position: "Директор",
};

/** Состояние демо-хранилища документов: одно письмо автора на подписи, ответ EDS о подписи — `signing`. */
const stateWith = (signing: Record<string, unknown>) => ({
  documents: [
    {
      id: ID,
      kind: "letter_out",
      number: null,
      status: "draft",
      version: 1,
      subject: "Ответ на требование ГНК",
      text: "Направляем пояснения.",
      ownerId: "u-demo-universal",
      amount: null,
      due_date: null,
      file_ids: [],
      erp_deal_id: null,
      recipient: { name: "ГНИ Мирабадского района", inn: null, company_id: "7", contact_id: null },
      decisions: [],
      created_at: AT,
      updated_at: AT,
      replyTo: null,
      signing,
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
        registration_requested: { ownerId: "u-demo-universal", at: AT },
      },
    },
  ],
  registry: [],
  files: {},
  next: { doc: 1000, memo: 100, application: 100, report: 100, outgoing: 100 },
});

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

type Scenario = {
  name: string;
  signing: Record<string, unknown>;
  check: (page: Page) => Promise<void>;
};

const SCENARIOS: Scenario[] = [
  {
    name: "author-handed-over",
    signing: DIRECTOR,
    check: async (page) => {
      await expect(page.getByText(/На подписи у Демо Директоров, Директор с /)).toBeVisible();
      await expect(
        page.getByText(
          "Вы автор письма. В компании включено правило: автор не подписывает своё письмо. Подписать может Демо Директоров.",
        ),
      ).toBeVisible();
      await expect(page.getByRole("button", { name: "Напомнить" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Отозвать" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Сменить подписанта" })).toBeVisible();
    },
  },
  {
    name: "author-signs-self",
    signing: { ...DIRECTOR, can_sign: true, reason: null },
    check: async (page) => {
      await expect(page.getByRole("button", { name: "Подписать самому" })).toBeVisible();
      await expect(page.getByText(/На подписи у Демо Директоров/)).toBeVisible();
      await expect(page.getByText(/Вы автор письма/)).toHaveCount(0);
    },
  },
  {
    name: "author-is-signer",
    signing: { can_sign: true, reason: null, signer_id: "u-demo-universal" },
    check: async (page) => {
      await expect(page.getByText(/Подписываете вы/)).toBeVisible();
      await expect(page.getByRole("button", { name: "Подписать", exact: true })).toBeVisible();
    },
  },
];

test.describe("ГЛ-0: письмо на подписи без тупика", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const scenario of SCENARIOS) {
    test(scenario.name, async ({ page }) => {
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
        if (page.url().startsWith("http")) {
          await page.evaluate(`window.localStorage.removeItem("rt-pf-mock-session")`);
        }
        await loginAndWait(page, "universal@demo.example");
        await page.evaluate(
          `window.localStorage.setItem("rt-pf-mock-eds-documents", ${JSON.stringify(JSON.stringify(stateWith(scenario.signing)))})`,
        );
        await spaGoto(page, `/eds/documents?scope=all&doc=${ID}&panel=open`);
        await expect(
          page.getByRole("heading", { level: 3, name: "Ответ на требование ГНК" }),
        ).toBeVisible();
        await scenario.check(page);
        // в боковой панели действия внизу: на снимке видны и подпись у кого, и кнопки
        await page.locator(".pf-fp-row").last().scrollIntoViewIfNeeded();
        const overflow = await page.evaluate<number>(
          "document.documentElement.scrollWidth - document.documentElement.clientWidth",
        );
        expect(overflow, `ширина ${String(width)}`).toBeLessThanOrEqual(0);
        const dir = process.env["E2E_SCREENSHOT_DIR"];
        if (dir) {
          await page.waitForTimeout(400);
          await page.screenshot({
            path: `${dir}/${scenario.name}-${String(width)}.png`,
            fullPage: true,
          });
        }
        await expectNoViolations(page, `axe ${scenario.name} ${String(width)}`);
      }
    });
  }

  test("signing-rule-setting", async ({ page }) => {
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
      if (page.url().startsWith("http")) {
        await page.evaluate(`window.localStorage.removeItem("rt-pf-mock-session")`);
      }
      await loginAndWait(page, "admin@demo.example");
      await spaGoto(page, "/admin/signing");
      const rule = page.getByRole("switch", { name: "Автор может подписать своё письмо" });
      await expect(rule).toBeChecked();
      await rule.scrollIntoViewIfNeeded();
      const dir = process.env["E2E_SCREENSHOT_DIR"];
      if (dir) {
        await page.waitForTimeout(400);
        await page.screenshot({ path: `${dir}/signing-rule-${String(width)}.png`, fullPage: true });
      }
      await expectNoViolations(page, `axe rule ${String(width)}`);
    }
  });
});
