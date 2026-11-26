import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { WEB_ROOT } from "../../ui-guards/detect.mjs";

/**
 * КАРКАС-1: содержимое страницы Настроек занимает доступную ширину. Страница-форма не сжимается до 560 / 768 px, а кладёт
 * карточки в сетку 1–3 колонок (`PageFrame`, ui-standard §9). Исключения — только в этих списках; они могут лишь
 * сокращаться (запись, которой больше нет, ломает тест).
 */
const ADMIN = join(WEB_ROOT, "src/modules/admin");

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}
const rel = (full: string) => full.slice(WEB_ROOT.length + 1);

/** Строка текста или поле поиска, а не страница: подпись ширины в `px` ≥ 480 вне `@media`. Путь → число правил. */
const WIDTH_EXCEPTIONS: Record<string, number> = {
  "src/modules/admin/settings/settings.css": 1, // строка поиска на «Состоянии»
  "src/modules/admin/bus/bus.css": 1, // абзац-пояснение, строка текста
};

/** Страницы, ещё стоящие вне каркаса (см. «Оставшиеся» в PR КАРКАС-1). */
const OUTSIDE_FRAME: readonly string[] = [];

function wideRules(css: string): number {
  const flat = css.replace(/@media[^{]*\{(?:[^{}]*\{[^}]*\})*[^}]*\}/g, "");
  return [...flat.matchAll(/max-width:\s*(\d+)px/g)].filter((m) => Number(m[1]) >= 480).length;
}

describe("page frame (КАРКАС-1)", () => {
  it("no page-level max-width in admin stylesheets beyond the baseline", () => {
    const found: Record<string, number> = {};
    for (const full of walk(ADMIN).filter((f) => f.endsWith(".css"))) {
      const n = wideRules(readFileSync(full, "utf8"));
      if (n > 0) found[rel(full)] = n;
    }
    expect(found).toEqual(WIDTH_EXCEPTIONS);
  });

  it("every admin page renders in the frame, except the shrinking list", () => {
    const outside: string[] = [];
    for (const full of walk(ADMIN)) {
      if (!/Page\.tsx$/.test(full) || /SettingsPage\.tsx$/.test(full)) continue;
      const text = readFileSync(full, "utf8");
      if (!/export function \w+Page\b/.test(text)) continue;
      if (!/<SettingsPage\b|<PageFrame\b/.test(text) && !/pages\.tsx$/.test(full))
        outside.push(rel(full));
    }
    expect(outside.sort()).toEqual([...OUTSIDE_FRAME].sort());
  });

  it("every object screen renders in the object layout, except the shrinking list", () => {
    const OBJECT_SCREENS = [
      "eds/inbox/LetterView",
      "eds/approvals/MemoView",
      "eds/drafts/QuoteView",
      "eds/projects/ProjectView",
      "eds/payments/PaymentView",
      "eds/payments/MemoView",
      "erp/stock/OrderScreen",
      "erp/stock/OrderCreatePage",
      "eds/new/NewDocumentPage",
      "eds/register/RegisterLetterPage",
      "eds/contracttpl/ContractTemplatesPage",
      "crm/kb/KbPage",
    ];
    const OBJECT_EXCEPTIONS: string[] = [];
    const outside = OBJECT_SCREENS.filter(
      (name) =>
        !readFileSync(join(WEB_ROOT, "src/modules", `${name}.tsx`), "utf8").includes(
          '<PageFrame layout="object">',
        ),
    );
    expect(outside).toEqual(OBJECT_EXCEPTIONS);
  });
});
