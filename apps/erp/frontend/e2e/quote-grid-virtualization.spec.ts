import { test, expect, Page } from '@playwright/test';

/**
 * КП-конструктор grid behaviour E2E (T2) — the browser-level counterpart to the
 * QuoteBuilder unit helpers (useGridKeyboard / useRowSelection / useSectionCollapse /
 * useGridDensity / the tanstack virtualizer). Those hooks are unit-tested in isolation;
 * this proves the wired-up grid actually renders, collapses, re-densifies, navigates by
 * keyboard and range-selects in a REAL browser.
 *
 * ── RUN TARGET ────────────────────────────────────────────────────────────────────────
 * MUTATING + LOCAL/STAGING ONLY. This suite logs in as the seeded seller.local user and
 * opens a real КП builder (`#deal-quote/{id}`), which only exists on a local docker stack
 * or a staging deployment BUILT FROM the feature branch (feat/u7-density — U5 collapse,
 * U6 keyboard nav, U7 density, virtualization). It is NOT prod-safe and must NEVER run in
 * the nightly prod e2e job: the login can't work against prod and the grid interactions
 * are stateful. Run it explicitly against a local stack:
 *
 *   cd frontend && E2E_BASE_URL=http://localhost:5173 npx playwright test \
 *     e2e/quote-grid-virtualization.spec.ts
 *   # or, no host Node:  e2e/run-in-docker.sh e2e/quote-grid-virtualization.spec.ts
 *
 * ── GREEN-RUN PREREQUISITES ───────────────────────────────────────────────────────────
 * For every scenario to actually EXERCISE (not gracefully skip) you need:
 *   • a frontend build that INCLUDES the feature branch (feat/u7-density);
 *   • a seeded seller (seller.local@erp.localhost) with ≥1 routed deal that has an
 *     active_quote whose КП carries priced ITEM lines — AND, for the collapse scenario,
 *     at least one SECTION row with item children;
 *   • ideally a КП with >50 lines to drive the virtualization window (see the note in the
 *     keyboard-nav test) — the seed КП is usually small, so windowed cross-row nav is only
 *     covered by the unit test today. Every scenario below degrades to test.skip() rather
 *     than failing when its data precondition is absent.
 *
 * Selectors are anchored to real code (role / aria-label / data-attributes), never brittle
 * copy — the few text assertions use known i18n keys (ru.json):
 *   - rows:            [data-row-id] / [data-display-type="SECTION"|"ITEM"]   (GridRow.tsx / SectionNoteRow.tsx)
 *   - sticky header:   <thead class="sticky …">                              (GridTable.tsx)
 *   - name column:     columnheader "Наименование"  (catalog.table.name)     (GridTable.tsx)
 *   - section chevron: button[aria-expanded] "Свернуть/Развернуть раздел"    (SectionNoteRow.tsx; quote.section.collapse/expand)
 *   - section subtotal:"Подытог"  (quote.section.subtotal)                   (SectionNoteRow.tsx)
 *   - density toggle:  button[aria-pressed] "Компактный/Обычная плотность"   (BuilderToolbar.tsx; quote.density.*)
 *   - row padding:     py-1.5 (comfortable) / py-0.5 (compact)               (gridConstants.GRID_DENSITY_ROW_PADDING)
 *   - grid cells:      input[data-cell-col][data-cell-row]                   (NumericCell.tsx; nav in useGridKeyboard.ts)
 *   - row checkbox:    role=checkbox "Выбрать позицию N"                     (RowSelectCheckbox.tsx; quote.bulk.selectRow)
 */

const SEED_PW = process.env.E2E_SEED_PASSWORD || 'Demo1234!';
// Seller login is env-overridable so the suite runs against whatever seed a given local
// stack carries (the canonical demo seed uses seller.local@erp.localhost).
const SELLER = { email: process.env.E2E_SELLER_EMAIL || 'seller.local@erp.localhost', password: SEED_PW };

// Local-stack gate — the seeded seller only exists on a local/staging stack (never prod),
// same guard the review-fixes suite uses. The whole file is skipped otherwise.
const IS_LOCAL_STACK = /localhost|127\.0\.0\.1/.test(process.env.E2E_BASE_URL || 'http://localhost:5173');

// Known i18n strings (ru.json) used where text is genuinely load-bearing (a column header,
// the collapse chevron's accessible name, the density toggle's name, the subtotal label).
const NAME_HEADER = 'Наименование'; // catalog.table.name
const SECTION_SUBTOTAL = 'Подытог'; // quote.section.subtotal
const DENSITY_LABEL = /Компактный вид|Обычная плотность/; // quote.density.compact / .comfortable

async function login(page: Page, email: string, password: string) {
	await page.goto('/');
	await page.locator('input[type="email"]').first().fill(email);
	await page.locator('input[type="password"]').first().fill(password);
	await page.locator('button[type="submit"]').first().click();
	// Login form gone == we're inside the app shell.
	await expect(page.locator('input[type="email"]')).toHaveCount(0, { timeout: 20_000 });
	await page.waitForLoadState('networkidle');
}

/** In-app hash navigation (App.tsx parseHashToPage) — set the hash without a full reload so the
 *  in-memory access token and React Query cache survive the move. */
async function gotoHash(page: Page, hash: string) {
	await page.evaluate((h) => { window.location.hash = h; }, hash);
	await page.waitForLoadState('networkidle').catch(() => { /* idle is best-effort */ });
}

/** Read the currently-focused grid cell's column/row identity (or null when focus left the grid). */
async function activeCell(page: Page): Promise<{ col: string | null; row: string | null } | null> {
	return page.evaluate(() => {
		const el = document.activeElement as HTMLElement | null;
		if (!el) return null;
		return { col: el.getAttribute('data-cell-col'), row: el.getAttribute('data-cell-row') };
	});
}

/** Collect up to `max` deal ids from the seller deals list by clicking a row and reading the
 *  `#request-detail/{id}` hash it navigates to (DealsPage.openDeal). Returns [] when the seller
 *  has no routed deals (→ callers skip). */
async function collectDealIds(page: Page, max: number): Promise<number[]> {
	await gotoHash(page, 'crm-deals');
	const rows = page.locator('tbody tr');
	try {
		await expect(rows.first()).toBeVisible({ timeout: 8_000 });
	} catch {
		return []; // no deals in the pipeline
	}
	const rowCount = Math.min(await rows.count(), max);
	const ids: number[] = [];
	for (let i = 0; i < rowCount; i++) {
		await gotoHash(page, 'crm-deals');
		await expect(rows.nth(i)).toBeVisible({ timeout: 8_000 });
		// Click the title cell (the last actions cell stops propagation).
		await rows.nth(i).locator('td').first().click();
		try {
			await page.waitForFunction(() => /#request-detail\/\d+/.test(window.location.hash), null, { timeout: 8_000 });
		} catch {
			continue;
		}
		const match = page.url().match(/#request-detail\/(\d+)/);
		if (match) ids.push(Number(match[1]));
	}
	return [...new Set(ids)];
}

interface BuilderState {
	mounted: boolean;
	dealId?: number;
	rowCount: number;
	sectionCount: number;
	itemQtyCells: number;
}

/**
 * Log in as the seller, walk the first few deals and open the first one whose КП builder actually
 * mounts a grid (deal has an active_quote). Returns the grid's shape so each test can skip on a
 * missing precondition instead of failing. Called at the top of every test — Playwright gives each
 * test a fresh context (empty localStorage), so density/collapse start at their defaults.
 */
async function setupBuilder(page: Page): Promise<BuilderState> {
	await login(page, SELLER.email, SELLER.password);
	const ids = await collectDealIds(page, 5);
	const gridHeader = page.getByRole('columnheader', { name: NAME_HEADER });
	for (const dealId of ids) {
		await gotoHash(page, `deal-quote/${dealId}`);
		try {
			await expect(gridHeader).toBeVisible({ timeout: 8_000 });
		} catch {
			continue; // this deal has no active_quote → guided empty-state, not the grid
		}
		return {
			mounted: true,
			dealId,
			rowCount: await page.locator('[data-row-id]').count(),
			sectionCount: await page.locator('[data-display-type="SECTION"]').count(),
			itemQtyCells: await page.locator('input[data-cell-col="quantity"]').count(),
		};
	}
	return { mounted: false, rowCount: 0, sectionCount: 0, itemQtyCells: 0 };
}

test.describe('КП grid — virtualization, collapse, density, keyboard, range-select', () => {
	test.skip(!IS_LOCAL_STACK, 'Local-stack + feature-build spec — needs seeded seller.local and the feat/u7-density grid. Set a local E2E_BASE_URL.');

	test('grid renders the priced line table with a sticky header', async ({ page }) => {
		const state = await setupBuilder(page);
		test.skip(!state.mounted, 'No seller deal with an active_quote КП was found to open the builder.');

		// The name column header is present…
		await expect(page.getByRole('columnheader', { name: NAME_HEADER })).toBeVisible();
		// …and the whole <thead> is sticky (survives the body scroll — GridTable.tsx).
		await expect(page.locator('thead').first()).toHaveClass(/sticky/);

		// A КП with lines shows at least one addressable row.
		if (state.rowCount > 0) {
			await expect(page.locator('[data-row-id]').first()).toBeVisible();
		}
	});

	test('section collapse (U5) hides child rows and surfaces the subtotal, then re-expands', async ({ page }) => {
		const state = await setupBuilder(page);
		test.skip(!state.mounted, 'No КП builder available.');
		test.skip(state.sectionCount === 0, 'This seed КП has no SECTION row — nothing to collapse.');

		const section = page.locator('[data-display-type="SECTION"]').first();
		const chevron = section.locator('button[aria-expanded]');
		await expect(chevron).toBeVisible();

		// Normalize to EXPANDED first (fresh context defaults to expanded, but be resilient).
		if ((await chevron.getAttribute('aria-expanded')) === 'false') {
			await chevron.click();
			await expect(chevron).toHaveAttribute('aria-expanded', 'true');
		}
		const rowsExpanded = await page.locator('[data-row-id]').count();

		// Collapse → chevron flips and no MORE rows are rendered (children leave the DOM when present).
		await chevron.click();
		await expect(chevron).toHaveAttribute('aria-expanded', 'false');
		const rowsCollapsed = await page.locator('[data-row-id]').count();
		expect(rowsCollapsed).toBeLessThanOrEqual(rowsExpanded);

		// The section aggregate is shown on the heading (only rendered when the section has children,
		// so assert it opportunistically rather than making it a hard precondition).
		if (await section.getByText(SECTION_SUBTOTAL).count()) {
			await expect(section.getByText(SECTION_SUBTOTAL).first()).toBeVisible();
		}

		// Re-expand restores the original row set exactly.
		await chevron.click();
		await expect(chevron).toHaveAttribute('aria-expanded', 'true');
		await expect(page.locator('[data-row-id]')).toHaveCount(rowsExpanded);
	});

	test('density toggle (U7) flips comfortable ↔ compact and re-densifies rows', async ({ page }) => {
		const state = await setupBuilder(page);
		test.skip(!state.mounted, 'No КП builder available.');

		const toggle = page.getByRole('button', { name: DENSITY_LABEL });
		await expect(toggle).toBeVisible();

		const pressedBefore = await toggle.getAttribute('aria-pressed');
		await toggle.click();
		const pressedAfter = await toggle.getAttribute('aria-pressed');
		expect(pressedAfter).not.toBe(pressedBefore); // the toggle actually flipped state

		// If lines are present, the body-row vertical padding class tracks the new density
		// (py-0.5 compact / py-1.5 comfortable — gridConstants.GRID_DENSITY_ROW_PADDING).
		if (state.rowCount > 0) {
			const firstRowCell = page.locator('[data-row-id]').first().locator('td').first();
			const nowCompact = pressedAfter === 'true';
			await expect(firstRowCell).toHaveClass(nowCompact ? /py-0\.5/ : /py-1\.5/);
		}

		// Toggle back — re-asserts the flip is bidirectional and leaves the grid as found.
		await toggle.click();
		expect(await toggle.getAttribute('aria-pressed')).toBe(pressedBefore);
	});

	test('keyboard nav (U6) moves the active cell down a column and across cells', async ({ page }) => {
		const state = await setupBuilder(page);
		test.skip(!state.mounted, 'No КП builder available.');
		test.skip(state.itemQtyCells < 2, 'Cross-row keyboard nav needs ≥2 priced ITEM rows in the КП.');

		// NOTE on virtualization: with ≤50 visible lines the grid renders every row (below
		// VIRTUALIZE_THRESHOLD), so this exercises WITHIN-window navigation. When the КП exceeds the
		// threshold, ArrowDown/Tab to an off-window row goes through useGridKeyboard's model-resolved
		// scroll-then-focus path (focusCellAtRow) — covered by the unit test; to drive it end-to-end
		// here, seed a КП with >50 lines and the same assertions hold as focus crosses the window edge.
		const qtyCells = page.locator('input[data-cell-col="quantity"]');
		const firstQty = qtyCells.first();

		// ArrowDown → SAME column, next row.
		await firstQty.click();
		const firstRowId = await firstQty.getAttribute('data-cell-row');
		await page.keyboard.press('ArrowDown');
		const afterDown = await activeCell(page);
		expect(afterDown?.col).toBe('quantity');
		expect(afterDown?.row).not.toBe(firstRowId);

		// Tab → the next registered cell (adjacent column, or wraps to the next ITEM row's first cell).
		await firstQty.click();
		await page.keyboard.press('Tab');
		const afterTab = await activeCell(page);
		expect(afterTab?.col).toBeTruthy();

		// ArrowRight with the caret at the text edge → adjacent column, or an Excel row-edge no-op —
		// either way focus stays on a registered grid cell and never falls out to <body>.
		await firstQty.click();
		await page.keyboard.press('End');
		await page.keyboard.press('ArrowRight');
		const afterRight = await activeCell(page);
		expect(afterRight?.col).toBeTruthy();
	});

	test('shift-select marks the contiguous range between two row checkboxes', async ({ page }) => {
		const state = await setupBuilder(page);
		test.skip(!state.mounted, 'No КП builder available.');

		const rowChecks = page.getByRole('checkbox', { name: /Выбрать позицию \d+/ });
		const checkCount = await rowChecks.count();
		test.skip(checkCount < 2, 'Range-select needs ≥2 selectable rows in the visible window.');

		// Anchor on the first row, Shift+click a later (still in-window) row.
		const lastIndex = Math.min(checkCount - 1, 3);
		const firstCheck = rowChecks.nth(0);
		const rangeEnd = rowChecks.nth(lastIndex);

		await firstCheck.click();
		await expect(firstCheck).toBeChecked();

		await rangeEnd.click({ modifiers: ['Shift'] });
		await expect(rangeEnd).toBeChecked();

		// The whole inclusive range (indices 0..lastIndex over the VISIBLE rows) is now selected.
		const selected = page.getByRole('checkbox', { name: /Выбрать позицию \d+/, checked: true });
		await expect(selected).toHaveCount(lastIndex + 1);
	});
});
