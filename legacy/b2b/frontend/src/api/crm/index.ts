/**
 * CRM API — пакет, собранный из монолитного crmApi.ts (1179 строк, 56 правок за три месяца:
 * самый горячий файл проекта по метрике «размер × частота изменений»).
 *
 * Разделено по доменам, а не по строкам. Публичный объект `crmApi` собирается здесь спредом,
 * поэтому его поверхность байт-в-байт та же, что была; `@/api/crmApi` остаётся барьером и
 * реэкспортирует и объект, и все типы — ни один из 97 импортирующих файлов не тронут.
 */

import { dealsApi } from './deals';
import { quoteItemsApi } from './quoteItems';
import { collabApi } from './collab';
import { quotesApi } from './quotes';
import { aiApi } from './ai';

export * from './types';
export * from './types.ai';

export const crmApi = {
	...dealsApi,
	...quoteItemsApi,
	...collabApi,
	...quotesApi,
	...aiApi,
};
