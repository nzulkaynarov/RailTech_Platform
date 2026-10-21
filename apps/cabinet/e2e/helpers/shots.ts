import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { expect, type Page } from '@playwright/test';
import { SCREENS_DIR } from './env';

const require = createRequire(import.meta.url);
const AXE_PATH = require.resolve('axe-core/axe.min.js');

export const WIDTHS = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
] as const;

interface AxeNode {
  target: unknown[];
  html: string;
}
interface AxeResults {
  violations: AxeViolation[];
  passes: unknown[];
}
interface AxeViolation {
  id: string;
  impact: 'minor' | 'moderate' | 'serious' | 'critical' | null;
  help: string;
  nodes: AxeNode[];
}

export interface ScreenReport {
  screen: string;
  width: number;
  /** axe запускался на этом экране (экраны CRM — только скриншоты). */
  axe: boolean;
  /** Сколько правил axe прошло (доказательство, что проверка реально отработала). */
  rulesPassed: number;
  /** Нарушения axe по степени: serious/critical проваливают прогон. */
  violations: { id: string; impact: string; help: string; nodes: number; sample: string }[];
  /** Горизонтальная прокрутка страницы на этой ширине: scrollWidth − innerWidth (должно быть ≤ 0). */
  overflowPx: number;
}

const reportFile = () => path.join(SCREENS_DIR, 'axe-summary.json');

function readReports(): ScreenReport[] {
  try {
    return JSON.parse(fs.readFileSync(reportFile(), 'utf8')) as ScreenReport[];
  } catch {
    return [];
  }
}

function writeReport(entry: ScreenReport): void {
  const all = readReports().filter((r) => !(r.screen === entry.screen && r.width === entry.width));
  all.push(entry);
  fs.mkdirSync(SCREENS_DIR, { recursive: true });
  fs.writeFileSync(reportFile(), `${JSON.stringify(all, null, 2)}\n`);
}

/** Страница дорисовалась: сеть затихла, шрифты загружены, скелетоны ушли. */
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => undefined);
  await page.evaluate(() => document.fonts.ready);
  await page.locator('[aria-busy="true"], .animate-pulse').first().waitFor({ state: 'detached', timeout: 5000 }).catch(() => undefined);
  // уведомление (sonner) появляется и гаснет с анимацией прозрачности: axe на полпути даёт ложный color-contrast —
  // ждём, пока оно уйдёт само (по умолчанию ~4 с), и снимаем экран без него
  await page.locator('[data-sonner-toast]').first().waitFor({ state: 'detached', timeout: 7000 }).catch(() => undefined);
  await page.waitForTimeout(250);
}

declare global {
  interface Window {
    axe: { run: (context: Document, options: object) => Promise<AxeResults> };
  }
}

async function runAxe(page: Page): Promise<{ violations: AxeViolation[]; passes: number }> {
  if (!(await page.evaluate(() => 'axe' in window))) await page.addScriptTag({ path: AXE_PATH });
  const result = await page.evaluate(() => window.axe.run(document, { resultTypes: ['violations', 'passes'] }));
  return { violations: result.violations, passes: result.passes.length };
}

/**
 * Скриншот текущего экрана на 1440 и 390 px (`<экран>-<ширина>.png` в docs/screens/fix-51b/), axe в браузере и
 * проверка горизонтальной прокрутки на каждой ширине. Нарушения serious/critical и прокрутка — `expect.soft`:
 * прогон не обрывается, дефекты видны в итоге и в `axe-summary.json`.
 */
export async function snap(page: Page, screen: string, options: { axe?: boolean; blocking?: boolean } = {}): Promise<void> {
  const withAxe = options.axe ?? true;
  fs.mkdirSync(SCREENS_DIR, { recursive: true });
  const original = page.viewportSize() ?? WIDTHS[0];
  try {
    for (const size of WIDTHS) {
      await page.setViewportSize(size);
      await settle(page);
      // Вся страница: окно растягивается по высоте документа (fullPage размазывал бы фиксированную нижнюю навигацию
      // телефона посреди экрана), снимок — обычный, как увидел бы человек с очень высоким экраном.
      const tall = await page.evaluate(() => document.documentElement.scrollHeight);
      if (tall > size.height) {
        await page.setViewportSize({ width: size.width, height: Math.min(tall, 3200) });
        await page.waitForTimeout(150);
      }
      await page.screenshot({ path: path.join(SCREENS_DIR, `${screen}-${size.width}.png`) });
      await page.setViewportSize(size);
      const axe = withAxe ? await runAxe(page) : { violations: [], passes: 0 };
      const violations = axe.violations;
      const overflowPx = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      writeReport({
        screen,
        width: size.width,
        axe: withAxe,
        rulesPassed: axe.passes,
        overflowPx,
        violations: violations.map((v) => ({
          id: v.id,
          impact: v.impact ?? 'unknown',
          help: v.help,
          nodes: v.nodes.length,
          sample: String(v.nodes[0]?.target?.[0] ?? '').slice(0, 120),
        })),
      });
      const blocking = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
      if (options.blocking === false) {
        // экран чужой системы (ERP, CRM): нарушения пишем в сводку и в консоль прогона, но не роняем гейт Cabinet
        if (blocking.length) console.log(`axe (не блокирует) — ${screen} @${size.width}: ${blocking.map((v) => `${v.id}: ${v.nodes.length}`).join(', ')}`);
      } else expect.soft(blocking.map((v) => `${v.id}: ${v.nodes.length}`), `axe serious/critical — ${screen} @${size.width}`).toEqual([]);
      if (options.blocking !== false) expect.soft(overflowPx, `горизонтальная прокрутка — ${screen} @${size.width}`).toBeLessThanOrEqual(0);
    }
  } finally {
    await page.setViewportSize(original);
  }
}
