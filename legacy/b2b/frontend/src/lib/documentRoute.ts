/**
 * Куда вести пользователя по ссылке на документ — с учётом его стороны (U1).
 *
 * Аудит UI 2026-07-30 нашёл 13 мест, где интерфейс показывал объект и вёл на страницу,
 * закрытую этой роли: покупателя — к актам, к билдеру КП, к очереди сделок; оператора — на
 * страницы, куда ведут его же экраны. Корень был один: **виджет показывает то, что вернул
 * сервер, а маршрут зашит константой**. Видимость считает бэкенд, доступ — статический
 * список ролей, и эти два источника правды разошлись.
 *
 * Здесь маршрут вычисляется ОДИН раз по типу документа и стороне зрителя. Виджеты больше не
 * решают, куда вести, — они спрашивают. Добавили новую поверхность — она получает правильную
 * ссылку бесплатно; ошибиться, как раньше, уже негде.
 *
 * Часть страниц двусторонние (договоры, счета, акты, отгрузка) — там маршрут один. Часть
 * принципиально ролевые: билдер КП правит цены и себестоимость, очередь сделок — рабочий
 * стол продавца. Для них у другой стороны есть СВОЙ вид того же объекта, и резолвер ведёт
 * туда, а не в отказ.
 */

/** Тип документа в терминах предметной области, а не страницы. */
export type DocumentKind = 'quote' | 'contract' | 'invoice' | 'act' | 'payment' | 'fulfillment' | 'generated';

export interface DocumentRouteInput {
  kind: DocumentKind;
  /** Идентификатор самого документа — для точечного `?open=`, если страница это умеет. */
  id?: number | null;
  /** Сделка, к которой относится документ: запасной маршрут для стороны без своей страницы. */
  dealId?: number | null;
}

export interface RouteViewer {
  /** Смотрит продавец (его рабочие места доступны). */
  isSeller: boolean;
  /** Платформенный оператор: своя навигация, часть бизнес-страниц ему закрыта. */
  isPlatformAdmin?: boolean;
}

/** Страницы, умеющие открывать конкретную запись через `?open=<id>`. */
const SUPPORTS_OPEN_PARAM = new Set(['contracts', 'invoices', 'acts']);

function pageWithId(page: string, id?: number | null): string {
  return id && SUPPORTS_OPEN_PARAM.has(page) ? `${page}?open=${id}` : page;
}

/**
 * Хэш-маршрут (без ведущего `#`), достижимый ДЛЯ ЭТОГО зрителя.
 *
 * Возвращает всегда что-то осмысленное: если у стороны нет своей страницы документа, ведём
 * на карточку сделки — там объект виден в блоке «Цепочка сделки».
 */
export function documentRoute(doc: DocumentRouteInput, viewer: RouteViewer): string {
  const { kind, id, dealId } = doc;
  const dealCard = dealId ? `request-detail/${dealId}` : null;

  switch (kind) {
    // Двусторонние документы: страница одна и открыта обеим сторонам.
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

    // КП: у продавца — билдер с ценами и маржой, у покупателя тот же документ виден на
    // карточке заявки. Вести покупателя в билдер нельзя — он там ничего не может.
    case 'quote':
      if (viewer.isSeller && dealId) return `deal-quote/${dealId}`;
      return dealCard ?? 'my-requests';

    // Произвольные документы — общий реестр у обеих сторон.
    case 'generated':
      return 'other-documents';

    default:
      return dealCard ?? 'dashboard';
  }
}

/**
 * Маршрут к самой сделке — для виджетов, которые ведут «к работе по сделке».
 *
 * У продавца это очередь сделок, у покупателя — его заявки. Раньше сюда зашивали
 * `crm-deals`, и покупателя из чата, воронки и обучающего тура выбрасывало на дашборд.
 */
export function dealsListRoute(viewer: RouteViewer): string {
  if (viewer.isPlatformAdmin) return 'admin-deals';
  return viewer.isSeller ? 'crm-deals' : 'my-requests';
}
