import AxeBuilder from "@axe-core/playwright";
import { type Page, expect } from "@playwright/test";

import { waitForMotionEnd } from "./app";

/**
 * axe (WCAG 2.1 AA) экрана: нарушений нет. Образцы документов — изолированные рамки (`iframe[sandbox]`): скрипты в них не
 * выполняются, axe не может опросить рамку и ждёт её до таймаута теста. Содержимое образца — документ ERP, а не интерфейс
 * Платформы; сама рамка (имя, размер) проверяется. С SET-IA образец бланка стоит на «Реквизиты и бланк» (`/admin/company`).
 */
export async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .exclude("iframe[sandbox]")
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}
