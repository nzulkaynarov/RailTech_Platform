import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { waitForMotionEnd } from "./support/app";

// Витрина общих компонентов `/dev/ui` (PLT-13): axe (WCAG 2.1 AA) на 1440 и 390, скриншоты всей страницы
// (`E2E_SCREENSHOT_DIR=<каталог>`) и размеры по таблицам docs/architecture/platform-frontend.md §4–§5, снятые с живой страницы.
const WIDTHS = [1440, 390] as const;

interface Box {
  width: number;
  height: number;
  color: string;
  background: string;
  border: string;
  radius: string;
  size: string;
  weight: string;
}

async function openShowcase(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  await page.goto("/dev/ui");
  await expect(
    page.getByRole("heading", { level: 1, name: "Витрина общих компонентов" }),
  ).toBeVisible();
  await waitForMotionEnd(page);
}

test.describe("витрина общих компонентов", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  for (const width of WIDTHS) {
    test(`на ${String(width)}: axe без нарушений, нет горизонтальной прокрутки`, async ({
      page,
    }) => {
      await openShowcase(page, width);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      expect(
        results.violations.map(
          (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
        ),
      ).toEqual([]);
      const overflow = await page.evaluate<number>(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth",
      );
      expect(overflow).toBeLessThanOrEqual(0);

      const dir = process.env["E2E_SCREENSHOT_DIR"];
      if (dir) {
        await page.waitForTimeout(500);
        await page.screenshot({ path: `${dir}/showcase-${String(width)}.png`, fullPage: true });
      }
    });
  }

  test("размеры и цвета на 1440 совпадают с platform-frontend.md §5", async ({ page }) => {
    await openShowcase(page, 1440);
    // Размеры и вычисленные стили первого элемента по селектору (скрипт строкой: в e2e нет типов DOM)
    const box = (selector: string) =>
      page.evaluate<Box>(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) throw new Error("нет элемента " + ${JSON.stringify(selector)});
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return {
          width: Math.round(r.width), height: Math.round(r.height), color: s.color,
          background: s.backgroundColor, border: s.borderTopColor, radius: s.borderTopLeftRadius,
          size: s.fontSize, weight: s.fontWeight,
        };
      })()`);

    // StatusTag: высота 22, радиус 4, шрифт 12
    const tag = await box(".ant-tag");
    expect(tag).toMatchObject({ height: 22, radius: "4px", size: "12px" });

    // RequestSteps: круг 24, подпись 13; пройденный — заливка #1668dc, текущий — #e6f4ff, рамка #1668dc
    const done = await box(".pf-step--done .pf-step-num");
    expect(done).toMatchObject({ width: 24, height: 24, background: "rgb(22, 104, 220)" });
    const current = await box(".pf-step--current .pf-step-num");
    expect(current).toMatchObject({
      width: 24,
      background: "rgb(230, 244, 255)",
      border: "rgb(22, 104, 220)",
      color: "rgb(9, 88, 217)",
    });
    expect(await box(".pf-step-label")).toMatchObject({ size: "13px" });
    const upcoming = await box(".pf-step--upcoming .pf-step-num");
    expect(upcoming).toMatchObject({ border: "rgb(217, 217, 217)", color: "rgb(89, 89, 89)" });

    // CounterCard: число 28/600, подпись 12
    expect(await box(".pf-counter-value")).toMatchObject({ size: "28px", weight: "600" });
    expect(await box(".pf-counter-label")).toMatchObject({
      size: "12px",
      color: "rgb(110, 110, 110)",
    });

    // History: точка 16
    expect(await box(".pf-history-dot")).toMatchObject({ width: 16, height: 16 });
    expect(await box(".pf-history-dot--done")).toMatchObject({ background: "rgb(35, 120, 4)" });

    // Checklist: строка 13 px
    expect(await box(".pf-check")).toMatchObject({ size: "13px" });

    // DocRow: первая колонка 150
    const columns = await page.evaluate<string>(
      `getComputedStyle(document.querySelector(".pf-doc")).gridTemplateColumns.split(" ")[0]`,
    );
    expect(columns).toBe("150px");

    // DefinitionList: подпись 130, цвет #595959
    const dt = await box(".pf-dl dt");
    expect(dt).toMatchObject({ width: 130, color: "rgb(89, 89, 89)" });

    // ContextPanel (закреплённое): 440, вкладки с активной линией #1668dc и текстом #0958d9
    expect(await box(".ant-layout-sider")).toMatchObject({ width: 440 });
    const activeTab = await box(".pf-panel-tabs .ant-tabs-tab-active .ant-tabs-tab-btn");
    expect(activeTab).toMatchObject({ color: "rgb(9, 88, 217)", weight: "500" });
    const ink = await box(".pf-panel-tabs .ant-tabs-ink-bar");
    expect(ink).toMatchObject({ height: 2, background: "rgb(22, 104, 220)" });
    const hide = await box("button[aria-label='Скрыть боковое окно']");
    expect(hide).toMatchObject({ width: 28, height: 28 });

    // Consequence: фон #fafafa, рамка #f0f0f0, радиус 8, шрифт 13
    expect(await box(".pf-consequence")).toMatchObject({
      background: "rgb(250, 250, 250)",
      border: "rgb(240, 240, 240)",
      radius: "8px",
      size: "13px",
    });

    // QueueList: отступ строки 14/24
    const padding = await page.evaluate<string>(
      `(() => { const s = getComputedStyle(document.querySelector(".pf-queue-row")); return s.paddingTop + " " + s.paddingLeft; })()`,
    );
    expect(padding).toBe("14px 24px");
  });
});
