import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, settledScreenshot, spaGoto } from "./support/app";
import { expectNoViolations } from "./support/axe";
import { expectFitsFrame } from "./support/layout";

// Polish pw2 · сторож раскладки на ключевых экранах (ноутбук 14″: 1512×982, и узкое окно 1280×800):
// страница не ползёт вбок, таблица не шире рамки (`expectFitsFrame`), заголовок страницы, строка фильтров и таблица
// не налезают друг на друга по рамкам элементов.

const SCREENS = [
  { name: "home", path: "/dashboard/queue" },
  { name: "leads", path: "/crm/leads" },
  { name: "clients", path: "/crm/clients" },
  { name: "counterparty-card", path: "/crm/clients?partner=2&panel=open&tab=card" },
  { name: "projects", path: "/eds/projects" },
  { name: "project-card", path: "/eds/projects/%D0%9F%D0%A0-2026-104" },
  { name: "documents", path: "/eds/documents?scope=all" },
  { name: "catalog", path: "/erp/catalog" },
  { name: "payments", path: "/eds/payments" },
  { name: "stock", path: "/erp/stock" },
  { name: "settings-employees", path: "/admin/org" },
  { name: "settings-zones", path: "/admin/zones" },
  { name: "state", path: "/admin" },
] as const;

const SIZES = [
  { width: 1512, height: 982 },
  { width: 1280, height: 800 },
] as const;

interface Box {
  name: string;
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/** Рамки заголовка страницы, строки фильтров и таблицы (если они есть на экране). */
async function blocks(page: Page): Promise<Box[]> {
  return page.evaluate<Box[]>(`(() => {
    const out = [];
    const take = (name, el) => {
      if (!el || el.offsetParent === null) return;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      out.push({ name, top: r.top, bottom: r.bottom, left: r.left, right: r.right });
    };
    const h1 = document.querySelector("main h1");
    take("header", h1 && h1.parentElement && h1.parentElement.parentElement);
    take("filters", document.querySelector("main .pf-filter-bar"));
    take("table", document.querySelector("main .pf-fp-scroll"));
    return out;
  })()`);
}

/** Блоки идут друг под другом: нижняя граница верхнего не ниже верхней границы нижнего более чем на 1 px. */
function overlaps(boxes: readonly Box[]): string[] {
  const found: string[] = [];
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i];
      const b = boxes[j];
      const wide = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const high = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (wide > 1 && high > 1) found.push(`${a.name} × ${b.name}`);
    }
  }
  return found;
}

test.describe("Polish pw2 · раскладка на 1512 и 1280", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("ключевые экраны: страница и таблицы в рамке, шапка, фильтры и таблица не налезают", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    for (const screen of SCREENS) {
      await spaGoto(page, screen.path);
      await expect(page.locator("main h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      await expectFitsFrame(page, screen.name);
      for (const size of SIZES) {
        await page.setViewportSize(size);
        await page.waitForTimeout(150);
        expect(overlaps(await blocks(page)), `${screen.name} · ${String(size.width)}`).toEqual([]);
      }
    }
  });

  test("слова: на ключевых экранах нет внутренних слов системы и должностей под аватаром, главная кнопка одна", async ({
    page,
  }) => {
    await loginAndWait(page, "director@demo.example");
    // словарь ui-standard §13: названия систем, разговорные слова, «Никто»
    const INTERNAL =
      /\b(CRM|ERP)\b|служебк|Платёжк|Бэк-офис|бэк-офис|Никто|Нет ответственного|Очередь отстаёт/;
    for (const screen of SCREENS) {
      await spaGoto(page, screen.path);
      await expect(page.locator("main h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      const text = await page.locator("main").innerText();
      expect(
        text.match(INTERNAL)?.[0] ?? null,
        `${screen.name}: внутреннее слово на экране`,
      ).toBeNull();
      const primaries = await page.locator("main .ant-btn-primary:visible").count();
      expect(primaries, `${screen.name}: главная кнопка одна`).toBeLessThanOrEqual(1);
    }
    // под аватаром должности нет: в левой колонке модулей остаются названия модулей и имя в подсказке
    await spaGoto(page, "/dashboard/queue");
    const rail = await page.getByRole("navigation", { name: "Модули" }).innerText();
    expect(rail).not.toMatch(/Директор|инженер|Бухгалтер/);
  });

  test("снимки 1512 и 390 и axe", async ({ page }) => {
    await loginAndWait(page, "director@demo.example");
    for (const screen of SCREENS) {
      await spaGoto(page, screen.path);
      await expect(page.locator("main h1").first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      for (const width of [1512, 390] as const) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 982 });
        await expectNoViolations(page, `${screen.name} ${String(width)}`);
        await settledScreenshot(page, screen.name);
      }
      await page.setViewportSize({ width: 1440, height: 900 });
    }
  });
});
