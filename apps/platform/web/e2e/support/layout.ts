import { type Page, expect } from "@playwright/test";

/** Ширины ноутбука 14″ (1512) и узкого окна (1280): таблицы обязаны помещаться в рамку на обеих. */
export const LAPTOP_WIDTHS = [1512, 1280] as const;

export interface Fit {
  /** `document.scrollWidth - clientWidth`: страница не ползёт вбок */
  page: number;
  /** Области прокрутки таблиц, чья таблица шире рамки: `имя → на сколько px` */
  tables: string[];
}

/** Замер: страница не шире окна, а таблица каждой области прокрутки (`.pf-fp-scroll`) не шире своей рамки. */
export async function measureFit(page: Page): Promise<Fit> {
  return page.evaluate<Fit>(`(() => {
    const root = document.documentElement;
    const tables = [];
    for (const region of document.querySelectorAll("main .pf-fp-scroll")) {
      const table = region.querySelector("table");
      if (!table || region.offsetParent === null) continue;
      const over = Math.round(table.getBoundingClientRect().width - region.clientWidth);
      if (over > 1 || region.scrollWidth - region.clientWidth > 1) {
        tables.push((region.getAttribute("aria-label") || "table") + " +" + String(Math.max(over, region.scrollWidth - region.clientWidth)));
      }
    }
    return { page: root.scrollWidth - root.clientWidth, tables };
  })()`);
}

/**
 * Проверка раскладки (polish pw1): на 1512 и 1280 страница не ползёт вбок и ни одна таблица не шире рамки. Окно
 * возвращается к ширине, с которой экран открыт.
 */
export async function expectFitsFrame(
  page: Page,
  context: string,
  widths: readonly number[] = LAPTOP_WIDTHS,
): Promise<void> {
  const before = page.viewportSize() ?? { width: 1440, height: 900 };
  for (const width of widths) {
    await page.setViewportSize({ width, height: 982 });
    // ширину таблица узнаёт через ResizeObserver — дать ей один кадр
    await page.waitForTimeout(150);
    const fit = await measureFit(page);
    expect(fit, `${context} · ${String(width)}`).toEqual({ page: 0, tables: [] });
  }
  await page.setViewportSize(before);
}
