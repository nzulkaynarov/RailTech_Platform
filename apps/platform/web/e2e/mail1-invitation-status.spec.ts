import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto, waitForMotionEnd } from "./support/app";

// B-MAIL-1 на MSW: в карточке клиента менеджер видит итог письма-приглашения в кабинет — «не отправлено: почта не
// настроена» словами — и «Отправить ещё раз»; после повтора — «в очереди», пока почтовый сервис не отправит письмо.
// 1440 и 390 (лист на весь экран), axe (WCAG 2.1 AA); снимки — docs/screens/mail1/.

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

const NOT_SENT =
  "не отправлено: Почта не настроена (Настройки · Подключения · Почта), письмо не отправлено.";

test(
  "карточка клиента: письмо приглашения не отправлено (почта не настроена) → «Отправить ещё раз» → в очереди",
  { tag: "@mobile" },
  async ({ page, isMobile }) => {
    await loginAndWait(page, "manager@demo.example");
    await spaGoto(page, "/crm/clients/6?panel=open&tab=card");
    const card = isMobile
      ? page.getByRole("dialog", { name: "Карточка клиента" })
      : page.locator("#pf-context-panel");
    const invitation = card.getByRole("region", { name: "Приглашение в кабинет" });
    await invitation.scrollIntoViewIfNeeded();
    await expect(invitation.getByText(NOT_SENT)).toBeVisible();
    await settledScreenshot(page, "invitation-not-sent");
    await expectNoViolations(page, "приглашение не отправлено");

    await invitation.getByRole("button", { name: "Отправить ещё раз" }).click();
    await expect(invitation.getByText("в очереди")).toBeVisible();
    await expect(
      invitation.getByText("Приглашение передано на отправку — итог появится здесь"),
    ).toBeVisible();
    if (isMobile) {
      const overflow = await page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth",
      );
      expect(overflow).toBe(0);
    }
    await settledScreenshot(page, "invitation-queued");
    await expectNoViolations(page, "приглашение в очереди");
  },
);
