import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { loginAndWait, spaGoto, waitForMotionEnd } from "./support/app";

// W18A-P2-4 «Отображение писем» на MSW: рассылка (HTML во фрейме, внешние картинки по кнопке, цитата под «…»,
// без горизонтальной прокрутки на 390 и без внутренней прокрутки фрейма) и ответ с цитатой и подписью (в карточке только
// новый текст, «…» раскрывает остальное). Обе ширины, axe.
const WIDTHS = [1440, 390] as const;
const REGISTRAR = "registrar@demo.example";
const MAIL_KEY = "rt-pf-mock-inbound-mail";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
async function expectNoViolations(page: Page, context: string): Promise<void> {
  await waitForMotionEnd(page);
  const results = await new AxeBuilder({ page })
    .exclude("iframe.pf-mail-frame")
    .withTags(TAGS)
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    context,
  ).toEqual([]);
}

/**
 * axe самого письма. Во фрейме скрипты запрещены, и AxeBuilder в него не заходит, поэтому тот же `srcdoc` открывается
 * целой страницей — вызывать в конце сценария: страница уходит с приложения.
 */
async function expectLetterAccessible(page: Page, context: string): Promise<void> {
  const html = await page.locator("iframe.pf-mail-frame").first().getAttribute("srcdoc");
  expect(html, context).not.toBeNull();
  await page.setContent(html ?? "");
  // имя документа во фрейме задаёт `title` самого `iframe`, поэтому document-title для копии не нужен
  const results = await new AxeBuilder({ page })
    .withTags(TAGS)
    .disableRules(["document-title"])
    .analyze();
  expect(
    results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    `${context}: письмо во фрейме`,
  ).toEqual([]);
}

async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env["E2E_SCREENSHOT_DIR"];
  if (!dir) return;
  await page.waitForTimeout(500);
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${dir}/${name}-${String(width)}.png`, fullPage: true });
}

/** Страница не шире экрана: на 390 никакой горизонтальной прокрутки. */
async function expectFits(page: Page, context: string): Promise<void> {
  const overflow = await page.evaluate<number>(
    "document.documentElement.scrollWidth - document.documentElement.clientWidth",
  );
  expect(overflow, context).toBeLessThanOrEqual(0);
}

async function signInAt(page: Page, width: number): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
  if (page.url().startsWith("http")) {
    await page.evaluate(
      `window.localStorage.removeItem("rt-pf-mock-session"); window.localStorage.removeItem("${MAIL_KEY}"); window.localStorage.removeItem("rt-pf-mock-imap-off")`,
    );
  }
  await loginAndWait(page, REGISTRAR);
}

interface FrameMetrics {
  sandbox: string;
  width: number;
  height: number;
  scrollWidth: number;
  bodyHeight: number;
  remote: number;
  csp: string | null;
}

/** Размеры содержимого фрейма: ни горизонтальной, ни внутренней вертикальной прокрутки. */
async function frameMetrics(page: Page): Promise<FrameMetrics | null> {
  return page.evaluate<FrameMetrics | null>(`(() => {
    const frame = document.querySelector("iframe.pf-mail-frame");
    const doc = frame && frame.contentDocument;
    const root = doc && doc.documentElement;
    if (!frame || !doc || !root || !doc.body.firstChild || doc.readyState !== "complete") return null;
    const meta = doc.querySelector('meta[http-equiv="Content-Security-Policy"]');
    return {
      sandbox: frame.getAttribute("sandbox") || "",
      width: frame.clientWidth,
      height: frame.clientHeight,
      scrollWidth: root.scrollWidth,
      bodyHeight: Math.ceil(doc.body.getBoundingClientRect().height),
      remote: doc.querySelectorAll('img[src^="http"]').length,
      csp: meta ? meta.getAttribute("content") : null,
    };
  })()`);
}

test.describe("P2-4: отображение писем", () => {
  test.skip(({ isMobile }) => isMobile, "ширины задаёт сам сценарий");

  test("рассылка: превью, письмо полностью во фрейме, картинки по кнопке", async ({ page }) => {
    for (const width of WIDTHS) {
      await signInAt(page, width);
      await spaGoto(page, "/eds/mail/19");
      await expect(
        page.getByRole("heading", { level: 1, name: "Скидки недели на канцтовары" }),
      ).toBeVisible();
      await expect(page.getByText("logo.png")).toHaveCount(0);
      await expect(page.locator("iframe")).toHaveCount(0);
      await shot(page, "newsletter-card");
      await expectFits(page, `карточка ${String(width)}`);
      await expectNoViolations(page, `карточка ${String(width)}`);

      await page.getByRole("button", { name: "Открыть письмо полностью" }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByTitle("Письмо «Скидки недели на канцтовары»")).toBeVisible();
      await waitForMotionEnd(page);
      await expect.poll(() => frameMetrics(page)).not.toBeNull();
      const closed = await frameMetrics(page);
      expect(closed?.sandbox).not.toContain("allow-scripts");
      expect(closed?.csp).toContain("default-src 'none'");
      expect(closed?.remote, "до клика ни одной внешней картинки").toBe(0);
      expect(closed?.scrollWidth ?? 0, `фрейм не шире панели ${String(width)}`).toBeLessThanOrEqual(
        (closed?.width ?? 0) + 1,
      );
      expect(
        closed?.height ?? 0,
        "высота по содержимому, без внутренней прокрутки",
      ).toBeGreaterThanOrEqual((closed?.bodyHeight ?? 1) - 1);
      await shot(page, "newsletter-full");
      await expectFits(page, `письмо полностью ${String(width)}`);
      await expectNoViolations(page, `письмо полностью ${String(width)}`);

      await dialog.getByRole("button", { name: "Показать картинки (2)" }).click();
      await expect(dialog.getByRole("button", { name: /Показать картинки/ })).toHaveCount(0);
      await expect.poll(async () => (await frameMetrics(page))?.remote).toBe(2);
      await shot(page, "newsletter-images");
      await expectFits(page, `с картинками ${String(width)}`);

      await expectLetterAccessible(page, `письмо ${String(width)}`);
    }
  });

  test("ответ с цитатой и подписью: только новый текст, остальное под «…»", async ({ page }) => {
    for (const width of WIDTHS) {
      await signInAt(page, width);
      await spaGoto(page, "/eds/mail/21");
      await expect(page.getByText(/Выставляем счёт на смазку/)).toBeVisible();
      await expect(page.getByText(/Подскажите цену смазки/)).toHaveCount(0);
      await shot(page, "reply-collapsed");
      const toggle = page.getByRole("button", { name: "Показать цитату и подпись" });
      await toggle.click();
      await expect(page.getByText(/Подскажите цену смазки/)).toBeVisible();
      await expect(page.getByText(/Демо-Масла, отдел продаж/)).toBeVisible();
      await shot(page, "reply-expanded");
      await expectFits(page, `цитата ${String(width)}`);
      await expectNoViolations(page, `цитата ${String(width)}`);
    }
  });

  test("обычное письмо: текст компактный, без внутреннего слайдера и пустот", async ({ page }) => {
    for (const width of WIDTHS) {
      await signInAt(page, width);
      await spaGoto(page, "/eds/mail/18");
      const text = page.locator("pre.pf-mail-text").first();
      await expect(text).toContainText("Просим направить коммерческое предложение");
      const box = await text.boundingBox();
      expect(box?.height ?? 0, "без огромных пустот").toBeLessThan(260);
      const scrolls = await page.evaluate<boolean>(
        `(() => { const el = document.querySelector("pre.pf-mail-text"); return el.scrollHeight > el.clientHeight + 1; })()`,
      );
      expect(scrolls, "у текста нет собственной прокрутки").toBe(false);
      expect(await text.innerText()).not.toMatch(/\n\s*\n\s*\n/);
      await shot(page, "plain-card");
      await expectFits(page, `обычное ${String(width)}`);
    }
  });
});
