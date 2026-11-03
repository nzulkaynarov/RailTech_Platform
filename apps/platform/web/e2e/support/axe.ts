import AxeBuilder from "@axe-core/playwright";
import { type Page, expect } from "@playwright/test";

import { waitForMotionEnd } from "./app";

/**
 * axe (WCAG 2.1 AA) экрана: нарушений нет. Образцы документов — изолированные рамки (`iframe[sandbox]`): скрипты в них не
 * выполняются, axe не может опросить рамку и ждёт её до таймаута теста, поэтому рамка исключена из axe целиком (вместе с ней
 * и правило `frame-title`). Имя рамки проверяет `expectSandboxFramesTitled`. С SET-IA образец бланка стоит на «Реквизиты и
 * бланк» (`/admin/company`).
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
  await expectSandboxFramesTitled(page, context);
}

/** Исключённые из axe рамки образцов всё же подписаны (`title`) — читалка экрана называет их (WCAG 4.1.2, frame-title). */
export async function expectSandboxFramesTitled(page: Page, context: string): Promise<void> {
  const frames = page.locator("iframe[sandbox]");
  const count = await frames.count();
  for (let index = 0; index < count; index += 1) {
    const title = (await frames.nth(index).getAttribute("title")) ?? "";
    expect(title.trim(), `${context}: title рамки образца`).not.toBe("");
  }
}
