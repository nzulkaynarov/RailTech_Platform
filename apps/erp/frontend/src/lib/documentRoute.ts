/**
 * Куда вести пользователя по ссылке на документ (U1).
 *
 * Аудит UI 2026-07-30 нашёл 13 мест, где интерфейс показывал объект и вёл на страницу,
 * которой для этого объекта нет. Корень был один: **виджет показывает то, что вернул сервер, а
 * маршрут зашит константой**. Здесь маршрут вычисляется ОДИН раз по типу документа: виджеты
 * больше не решают, куда вести, — они спрашивают. Добавили новую поверхность — она получает
 * правильную ссылку бесплатно.
 *
 * ERP — бэк-офис одной компании (M1-ERP-02 волна 3): стороны зрителя («покупатель / продавец»)
 * больше нет, маршрут зависит только от документа. Клиентский вид тех же документов — в Cabinet.
 */

/** Тип документа в терминах предметной области, а не страницы. */
export type DocumentKind = 'quote' | 'contract' | 'invoice' | 'act' | 'payment' | 'fulfillment' | 'generated' | 'receipt' | 'delivery_note';

export interface DocumentRouteInput {
  kind: DocumentKind;
  /** Идентификатор самого документа — для точечного `?open=`, если страница это умеет. */
  id?: number | null;
  /** Сделка, к которой относится документ: билдер КП и запасной маршрут. */
  dealId?: number | null;
}

/** Страницы, умеющие открывать конкретную запись через `?open=<id>`. */
const SUPPORTS_OPEN_PARAM = new Set(['contracts', 'invoices', 'acts']);

function pageWithId(page: string, id?: number | null): string {
  return id && SUPPORTS_OPEN_PARAM.has(page) ? `${page}?open=${id}` : page;
}

/**
 * Хэш-маршрут (без ведущего `#`) к документу.
 *
 * Возвращает всегда что-то осмысленное: если у документа нет своей страницы, ведём на карточку
 * сделки — там объект виден в блоке «Цепочка сделки».
 */
export function documentRoute(doc: DocumentRouteInput): string {
  const { kind, id, dealId } = doc;
  const dealCard = dealId ? `request-detail/${dealId}` : null;

  switch (kind) {
    case 'contract':
      return pageWithId('contracts', id);
    case 'invoice':
      return pageWithId('invoices', id);
    case 'act':
      return pageWithId('acts', id);
    case 'payment':
      return 'payments';
    case 'fulfillment':
      return 'fulfillments';
    // D2: печатные артефакты регистров — ведём на их регистр (там кнопка скачивания).
    case 'receipt':
      return 'payments';
    case 'delivery_note':
      return 'fulfillments';

    // КП — билдер с ценами и маржой; без сделки — реестр КП.
    case 'quote':
      return dealId ? `deal-quote/${dealId}` : 'crm-quotes';

    // Произвольные документы — общий реестр.
    case 'generated':
      return 'other-documents';

    default:
      return dealCard ?? 'dashboard';
  }
}

/** Маршрут «к работе по сделкам» — очередь сделок бэк-офиса. */
export const DEALS_LIST_ROUTE = 'crm-deals';
