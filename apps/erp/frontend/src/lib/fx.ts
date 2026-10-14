import { toDecimal } from '@/utils/decimal';
import { formatNumber } from '@/lib/formatLocale';

/**
 * Курс валюты для показа (M1-ERP-08): «12 650,55» — минимум 2 знака, до 6 значащих после запятой.
 * Курс — строка API; арифметики здесь нет, только показ.
 */
export function formatFxRate(rate: string | null | undefined): string {
	if (rate === null || rate === undefined || rate === '') return '—';
	return formatNumber(toDecimal(rate).toNumber(), { minimumFractionDigits: 2, maximumFractionDigits: 6 });
}

const SOURCE_KEYS: Record<string, string> = {
	CBU: 'quote.fx.source.CBU',
	MANUAL: 'quote.fx.source.MANUAL',
	OVERRIDE: 'quote.fx.source.OVERRIDE',
	BASE: 'quote.fx.source.BASE',
};

/** Ключ i18n источника курса (CBU / MANUAL / OVERRIDE); неизвестный — общий «справочник». */
export function fxSourceLabelKey(source: string | null | undefined): string {
	return SOURCE_KEYS[(source ?? '').toUpperCase()] ?? 'quote.fx.source.MANUAL';
}
