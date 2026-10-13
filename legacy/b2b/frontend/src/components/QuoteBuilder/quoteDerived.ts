/**
 * Производные значения КП — чистые функции от активного КП, без хуков и без состояния.
 *
 * Вынесено из QuoteBuilderGrid: это самый горячий файл проекта (49 правок за три месяца), и
 * четверть его объёма занимала арифметика «во что развернуть active_quote». Здесь она отделена
 * от оркестрации, поэтому правка курса/колонок больше не заставляет читать весь грид.
 */

import type { Quote, QuoteItem } from '@/api/crmApi';
import { toDecimal } from '@/utils/decimal';

/** Курс (сум за 1 единицу) для валюты строки: ручной override важнее замороженного снапшота. */
export const makeFxRateFor = (quote: Quote) => (code?: string): string => {
	const ccy = (code || 'UZS').toUpperCase();
	if (ccy === 'UZS') return '1';
	const fxManual = quote.fx_manual ?? {};
	const fxSnapshot = quote.fx_snapshot ?? {};
	const fxMarket = quote.fx_market ?? {};
	return fxManual[ccy] || fxSnapshot[ccy] || fxMarket[ccy] || '1';
};

/** Себестоимость строки в презентационной валюте (UZS) — для тултипа. */
export const makeLineCostInPresentation =
	(fxRateFor: (code?: string) => string) =>
	(item: QuoteItem): string => {
		const native = toDecimal(item.frozen_base_price).plus(toDecimal(item.customs_duty));
		return native.mul(toDecimal(fxRateFor(item.frozen_currency))).toString();
	};

/** Человекочитаемое имя поля строки КП — подписывает скрытые поля в маркере ошибки. */
export const makeFieldLabel = (t: (key: string) => string) => (field: string): string => {
	const labels: Record<string, string> = {
		customs_duty: t('quote.customsDuty'),
		discount_percent: t('quote.discountPercent'),
		lead_time_days: t('quote.leadTime'),
		hs_code: t('quote.hsCode'),
		frozen_base_price: t('quote.basePrice'),
		frozen_currency: t('quote.lineCurrency'),
		margin_percent: t('quote.marginOverride.header'),
	};
	return labels[field] ?? field;
};

export interface QuoteViewDerived {
	presentationCurrency: string;
	vatRate: string;
	econ: NonNullable<Quote['economics']> | null;
	canViewCost: boolean;
	showCostColumns: boolean;
	effectiveLeadTime: number;
	mainColCount: number;
	fxRateFor: (code?: string) => string;
	lineCostInPresentation: (item: QuoteItem) => string;
}

/**
 * Разворачивает активное КП в набор значений, которыми пользуется грид.
 *
 * `isCompact` — вьюпорт-гейт поверх прав: ниже 1200px две колонки себестоимости уходят из
 * основной таблицы (экономика остаётся в раскрытой строке).
 */
export function deriveQuoteView(quote: Quote, isCompact: boolean): QuoteViewDerived {
	// Гейт «видит себестоимость»: сервер РЕДАКТИРУЕТ cost-поля и отдаёт economics === null без
	// права quote.view_cost_margin. Один производный флаг управляет всеми cost-колонками и панелями.
	const econ = quote.economics ?? null;
	const canViewCost = !!econ;
	const showCostColumns = canViewCost && !isCompact;
	const fxRateFor = makeFxRateFor(quote);
	return {
		// Все ХРАНИМЫЕ итоги в UZS; вычисляемые колонки рендерятся в презентационной валюте.
		presentationCurrency: quote.quote_currency || 'UZS',
		vatRate: quote.vat_rate || '12',
		econ,
		canViewCost,
		showCostColumns,
		effectiveLeadTime: quote.effective_delivery_lead_time_days ?? 0,
		// Видимые колонки основной строки (для detail-строки и colSpan распорки): выбор, шеврон,
		// имя, кол-во, [база], [маржа], сумма, удалить — минус две cost-колонки под гейтом <1200px.
		mainColCount: showCostColumns ? 8 : 6,
		fxRateFor,
		lineCostInPresentation: makeLineCostInPresentation(fxRateFor),
	};
}
