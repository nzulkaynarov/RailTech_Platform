/**
 * CRM-хуки — пакет, собранный из монолитного useCRM.ts (727 строк, 39 правок).
 *
 * Домены зеркалят пакет `@/api/crm`, поэтому «где лежит запрос» и «где лежит хук к нему»
 * теперь один и тот же вопрос. Путь `@/hooks/useCRM` сохранён барьером (41 импортёр).
 */

export * from './deals';
export * from './quoteItems';
export * from './collab';
export * from './quotes';
export * from './charges';
export * from './quoteLifecycle';
export * from './leadsAi';
