import { describe, it, expect } from 'vitest';

import {
	parseClipboardTable,
	detectColumnRoles,
	normalizeNumericString,
	toBulkCreateRows,
	shouldInterceptClipboardPaste,
} from '@/components/QuoteBuilder/parseClipboardTable';

/**
 * Excel-paste parser (spec §5 п.12). Sellers' заявки live in Excel; the seller copies a
 * tab-separated table and pastes it into the КП grid. These tests pin the parsing, number
 * normalization, column heuristic, row-cap and paste-interception decision.
 */
describe('parseClipboardTable', () => {
	it('splits a tab-separated block into rows and columns', () => {
		const table = parseClipboardTable('Болт М12\t100\t2500\nГайка М12\t200\t900');
		expect(table.columnCount).toBe(3);
		expect(table.rows).toEqual([
			['Болт М12', '100', '2500'],
			['Гайка М12', '200', '900'],
		]);
	});

	it('handles CRLF line endings (Windows Excel)', () => {
		const table = parseClipboardTable('Rail A\t5\r\nRail B\t7\r\n');
		expect(table.rows).toEqual([
			['Rail A', '5'],
			['Rail B', '7'],
		]);
	});

	it('drops fully-empty rows and trailing empty columns', () => {
		// A blank separator line + a trailing tab column that Excel commonly appends.
		const table = parseClipboardTable('Item\t10\t\n\n\nOther\t20\t');
		expect(table.columnCount).toBe(2);
		expect(table.rows).toEqual([
			['Item', '10'],
			['Other', '20'],
		]);
	});

	it('returns an empty table for blank / whitespace-only input', () => {
		expect(parseClipboardTable('').rows).toEqual([]);
		expect(parseClipboardTable('   \n  \n').rows).toEqual([]);
		expect(parseClipboardTable(null).columnCount).toBe(0);
	});

	it('treats a single column as the name column', () => {
		const table = parseClipboardTable('Первая\nВторая\nТретья');
		expect(table.columnCount).toBe(1);
		expect(table.roles).toEqual(['name']);
	});
});

describe('normalizeNumericString', () => {
	it('accepts a comma decimal (RU locale)', () => {
		expect(normalizeNumericString('1234,50')).toBe('1234.50');
	});

	it('strips space / NBSP thousands separators', () => {
		expect(normalizeNumericString('1 234,50')).toBe('1234.50');
		expect(normalizeNumericString('1 234 567')).toBe('1234567');
	});

	it('resolves mixed comma+dot by the last separator being decimal', () => {
		expect(normalizeNumericString('1.234,50')).toBe('1234.50');
		expect(normalizeNumericString('1,234.50')).toBe('1234.50');
	});

	it('treats multiple commas as thousands grouping', () => {
		expect(normalizeNumericString('1,234,567')).toBe('1234567');
	});

	it('rejects non-numeric cells', () => {
		expect(normalizeNumericString('Болт М12')).toBeNull();
		expect(normalizeNumericString('')).toBeNull();
		expect(normalizeNumericString(null)).toBeNull();
	});
});

describe('detectColumnRoles heuristic', () => {
	it('picks the first textual column as name, then numeric columns as quantity/price', () => {
		const rows = [
			['Болт', '100', '2500'],
			['Гайка', '200', '900'],
		];
		expect(detectColumnRoles(rows, 3)).toEqual(['name', 'quantity', 'price']);
	});

	it('finds the name column even when it is not first', () => {
		const rows = [
			['100', 'Болт', '2500'],
			['200', 'Гайка', '900'],
		];
		expect(detectColumnRoles(rows, 3)).toEqual(['quantity', 'name', 'price']);
	});
});

describe('toBulkCreateRows', () => {
	it('builds bulk-create payload rows from mapped columns', () => {
		const table = parseClipboardTable('Болт\t100\t2 500,50\nГайка\t200\t900');
		const rows = toBulkCreateRows(table, table.roles, 500);
		expect(rows).toEqual([
			{ imported_raw_name: 'Болт', quantity: 100, frozen_base_price: '2500.50' },
			{ imported_raw_name: 'Гайка', quantity: 200, frozen_base_price: '900' },
		]);
	});

	it('omits quantity / price when the cell is not numeric or the column is unmapped', () => {
		const table = parseClipboardTable('Только имя');
		const rows = toBulkCreateRows(table, ['name'], 500);
		expect(rows).toEqual([{ imported_raw_name: 'Только имя' }]);
	});

	it('truncates to maxRows (server cap 500)', () => {
		const source = Array.from({ length: 520 }, (_unused, index) => `Позиция ${index}\t1`).join('\n');
		const table = parseClipboardTable(source);
		expect(table.rows.length).toBe(520);
		const rows = toBulkCreateRows(table, table.roles, 500);
		expect(rows.length).toBe(500);
		expect(rows[499].imported_raw_name).toBe('Позиция 499');
	});
});

describe('shouldInterceptClipboardPaste', () => {
	it('intercepts multi-row tabular text regardless of target', () => {
		expect(shouldInterceptClipboardPaste('A\t1\nB\t2', false)).toBe(true);
		expect(shouldInterceptClipboardPaste('A\t1\nB\t2', true)).toBe(true);
	});

	it('intercepts a single tab-separated line', () => {
		expect(shouldInterceptClipboardPaste('Болт\t100\t2500', true)).toBe(true);
	});

	it('does NOT intercept a single-cell paste into an editable input', () => {
		expect(shouldInterceptClipboardPaste('2500', true)).toBe(false);
		expect(shouldInterceptClipboardPaste('Просто текст', true)).toBe(false);
	});

	it('does not intercept empty text', () => {
		expect(shouldInterceptClipboardPaste('', false)).toBe(false);
	});
});
