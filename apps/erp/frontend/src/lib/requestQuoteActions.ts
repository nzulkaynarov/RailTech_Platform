/**
 * FIX-67 — какие кнопки создания КП показывает карточка заявки.
 *
 * Было: «Создать КП» прятали, когда у сотрудника есть право на цены (`!canTakeAndPrepare`), а
 * «Взять в работу и подготовить» показывали на ЛЮБОЙ заявке без КП — и на заявке без строк она
 * кончалась отказом `NO_REQUEST_LINES`. Из заявки нельзя было сделать КП вообще.
 *
 * Стало (две независимые кнопки):
 *  • «Создать КП» — всегда, пока КП не начато и есть право на создание КП (`quote.edit_pricing`:
 *    ровно то, что проверяет сервер на `POST crm/quotes/`);
 *  • «Взять в работу и подготовить» — только когда у заявки есть строки, которые есть кому копировать.
 *    Число строк считает сервер (`Deal.request_lines_count`): фронт не угадывает, где они лежат.
 */
export interface RequestQuoteEntryInput {
  /** КП ещё не собирали (`needsQuoteWork`: пред-КП стадия, КП нет или пустой черновик без денег). */
  quoteNotStarted: boolean;
  /** Право `quote.edit_pricing`. */
  canEditPricing: boolean;
  /** Строк в заявке клиента. */
  requestLinesCount: number;
}

export function requestQuoteEntryActions({ quoteNotStarted, canEditPricing, requestLinesCount }: RequestQuoteEntryInput) {
  const canBuildQuote = quoteNotStarted && canEditPricing;
  const canTakeAndPrepare = canBuildQuote && requestLinesCount > 0;
  return { canBuildQuote, canTakeAndPrepare };
}
