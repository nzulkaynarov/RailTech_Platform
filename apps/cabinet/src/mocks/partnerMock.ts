import type { Schemas } from '@/api/portal';

/**
 * Данные и правила мока раздела «Мои товары» (PART-2): те же, что у ERP (`portal/services/partner_products.py`) —
 * вкладки по статусам, своя цена, отправка на проверку (только свои черновики и возвращённые), подтверждение актуальности
 * (цена с истёкшим сроком не подтверждается), загрузка прайса с предпросмотром. «Сегодня» мока — 2026-10-14.
 *
 * Сценарии прайса по имени файла: `broken` — нет колонки «Наименование» (файл не принят), `errors` — три строки с ошибками
 * и замечание по коду ТН ВЭД, `existing` — товар, который уже есть в каталоге (предложения изменений), иначе — чистый файл
 * на три новых карточки.
 */
type Product = Schemas['PartnerProduct'];
type Detail = Schemas['PartnerProductDetail'];
type Task = { dryRun: boolean; fileName: string; polls: number; applied: boolean };

function offer(price: string, over: Partial<Schemas['PartnerOffer']> = {}): Schemas['PartnerOffer'] {
  return {
    price: { amount: price, currency: 'USD' },
    valid_from: '2026-09-01',
    valid_until: '2027-03-01',
    delivery_basis: 'FCA',
    min_order_qty: 10,
    confirmed_at: '2026-10-10T09:00:00+05:00',
    freshness: 'fresh',
    ...over,
  };
}

function card(id: number, name: string, over: Partial<Product>): Product {
  return {
    id,
    name,
    brand: 'Аквилон',
    manufacturer_part_number: `AQ-${id}`,
    category: 'Тормозные системы',
    status: 'draft',
    return_reason: null,
    return_issues: [],
    completeness: 100,
    offer: offer('120.00'),
    has_pending_change: false,
    is_own: true,
    can_submit: true,
    updated_at: '2026-10-12T10:00:00+05:00',
    ...over,
  };
}

export function partnerProducts(): Product[] {
  return [
    card(9001, 'Тормозная колодка композитная', { offer: offer('150.50') }),
    card(9002, 'Подшипник 6205-2RS', {
      manufacturer_part_number: '6205-2RS',
      brand: 'Норд',
      category: null,
      completeness: 75,
      offer: offer('4.20', { confirmed_at: '2026-08-20T09:00:00+05:00', freshness: 'stale' }),
    }),
    card(9003, 'Фильтр масляный', {
      offer: offer('8.75', { valid_until: '2026-10-18', freshness: 'expiring' }),
    }),
    card(9004, 'Втулка резиновая', { status: 'review', can_submit: false, offer: offer('2.10') }),
    card(9005, 'Кабель силовой 3×2,5', {
      status: 'returned',
      manufacturer_part_number: '',
      completeness: 80,
      return_reason: 'Не указан артикул производителя, и категория выбрана неверно.',
      return_issues: [
        { field: 'manufacturer_part_number', comment: 'Укажите артикул по шильдику изделия' },
        { field: 'category', comment: 'Кабель относится к «Электротехнике», а не к «Крепежу»' },
      ],
      offer: offer('1.35'),
    }),
    card(9006, 'Болт М12×60 оцинкованный', {
      status: 'published',
      can_submit: false,
      has_pending_change: true,
      offer: offer('0.18'),
    }),
    card(9007, 'Гайка М12', {
      status: 'published',
      can_submit: false,
      offer: offer('0.06', { valid_until: '2026-09-30', freshness: 'expired' }),
    }),
    // Цена привязалась к чужой неопубликованной карточке: только то, что партнёр прислал сам (название строки, бренд, артикул)
    card(9008, 'Уплотнитель дверной', {
      status: 'matched',
      is_own: false,
      can_submit: false,
      brand: 'Аквилон',
      category: null,
      completeness: 0,
      manufacturer_part_number: 'SEAL-D1',
      offer: offer('3.40'),
    }),
  ];
}

const MISSING: Record<number, Array<{ code: string; label: string }>> = {
  9002: [{ code: 'category', label: 'Категория' }],
  9005: [{ code: 'identity', label: 'Артикул производителя или ГОСТ' }],
};

export function detailOf(product: Product): Detail {
  const history: Detail['history'] = [];
  if (product.is_own && product.status === 'returned') {
    history.push(
      { submitted_at: '2026-10-08T11:00:00+05:00', decision: 'returned', reason: product.return_reason ?? '', issues: product.return_issues, decided_at: '2026-10-09T10:30:00+05:00' },
    );
  }
  if (product.is_own && product.status === 'review') {
    history.push({ submitted_at: '2026-10-13T16:20:00+05:00', decision: 'pending', reason: '', issues: [], decided_at: null });
  }
  if (product.is_own && product.status === 'published') {
    history.push({ submitted_at: '2026-09-25T12:00:00+05:00', decision: 'published', reason: '', issues: [], decided_at: '2026-09-26T09:40:00+05:00' });
  }
  if (product.status === 'matched') return { ...product, description: '', hs_code: '', uom: null, missing: [], history: [] };
  return {
    ...product,
    description: product.is_own ? `Описание: ${product.name}.` : '',
    hs_code: product.is_own ? '8708301009' : '',
    uom: 'шт',
    missing: MISSING[product.id] ?? [],
    history,
  };
}

export function statusCounts(items: Product[]): Schemas['PartnerStatusCounts'] {
  const count = (status: Schemas['PartnerCardStatus']) => items.filter((item) => item.status === status).length;
  return {
    all: items.length,
    draft: count('draft'),
    review: count('review'),
    returned: count('returned'),
    published: count('published'),
    matched: count('matched'),
  };
}

export function attention(items: Product[]): Schemas['PartnerAttention'] {
  const count = (freshness: Schemas['OfferFreshness']) => items.filter((item) => item.offer?.freshness === freshness).length;
  return { expired: count('expired'), stale: count('stale'), expiring: count('expiring') };
}

export function submitIds(items: Product[], ids: number[]): Schemas['PartnerSubmitResult'] {
  const submitted: number[] = [];
  const errors: Schemas['PartnerItemError'][] = [];
  for (const id of [...new Set(ids)]) {
    const item = items.find((candidate) => candidate.id === id);
    if (!item || !item.is_own) errors.push({ id, code: 'NOT_FOUND' });
    else if (!item.can_submit) errors.push({ id, code: 'PRODUCT_NOT_SUBMITTABLE' });
    else {
      item.status = 'review';
      item.can_submit = false;
      item.return_reason = null;
      item.return_issues = [];
      submitted.push(id);
    }
  }
  return { submitted, errors };
}

export function confirmIds(items: Product[], ids: number[] | null): Schemas['PartnerConfirmResult'] {
  const targets = ids === null ? items.filter((item) => item.offer) : ids.map((id) => items.find((item) => item.id === id));
  let confirmed = 0;
  let expired = 0;
  const errors: Schemas['PartnerItemError'][] = [];
  targets.forEach((item, index) => {
    if (!item?.offer) {
      errors.push({ id: ids?.[index] ?? 0, code: 'NOT_FOUND' });
    } else if (item.offer.freshness === 'expired') {
      expired += 1;
      if (ids !== null) errors.push({ id: item.id, code: 'OFFER_EXPIRED' });
    } else {
      item.offer.confirmed_at = new Date().toISOString();
      item.offer.freshness = item.offer.freshness === 'expiring' ? 'expiring' : 'fresh';
      confirmed += 1;
    }
  });
  return { confirmed, expired, errors };
}

export function newTask(fileName: string, dryRun: boolean): Task {
  return { dryRun, fileName, polls: 0, applied: false };
}

function baseReport(dryRun: boolean): Schemas['PriceListReport'] {
  return {
    dry_run: dryRun,
    created: 3,
    updated: 0,
    offers_created: 3,
    offers_updated: 0,
    proposal_count: 0,
    proposals: [],
    error_count: 0,
    errors: [],
    warning_count: 0,
    warnings: [],
    rows_truncated: 0,
    unpublishable: 1,
    missing_breakdown: [{ code: 'category', label: 'Категория', count: 1 }],
  };
}

/** Состояние задачи: первый опрос — «идёт обработка», следующий — результат (как у настоящей очереди). */
export function taskView(taskId: string, task: Task, items: Product[]): Schemas['PriceListTask'] {
  task.polls += 1;
  if (task.polls === 1) return { task_id: taskId, status: 'running', error: null, report: null };
  if (task.fileName.includes('broken')) {
    return { task_id: taskId, status: 'failed', error: 'NAME_COLUMN_NOT_FOUND', report: null };
  }
  const report = baseReport(task.dryRun);
  if (task.fileName.includes('errors')) {
    report.created = 2;
    report.error_count = 3;
    report.offers_created = 2;
    report.errors = [
      { row: 4, field: 'price', code: 'PRICE_NOT_A_NUMBER', value: null },
      { row: 7, field: 'category', code: 'UNKNOWN_CATEGORY', value: 'Крепёж' },
      { row: 12, field: 'currency', code: 'UNKNOWN_CURRENCY', value: 'US' },
    ];
    report.warning_count = 1;
    report.warnings = [{ row: 9, field: 'hs_code', code: 'HS_CODE_NOT_IN_CLASSIFIER', value: '8708309999' }];
  } else if (task.fileName.includes('existing')) {
    report.created = 1;
    report.updated = 2;
    report.offers_created = 1;
    report.offers_updated = 2;
    report.proposal_count = 2;
    report.proposals = [
      { row: 3, field: 'name' },
      { row: 5, field: 'category' },
    ];
  }
  if (!task.dryRun && !task.applied) {
    task.applied = true;
    const base = Math.max(...items.map((item) => item.id)) + 1;
    for (let index = 0; index < report.created; index += 1) {
      items.unshift(
        card(base + index, `Новая позиция из прайса ${index + 1}`, {
          offer: offer('12.00', { confirmed_at: new Date().toISOString() }),
        }),
      );
    }
  }
  return { task_id: taskId, status: 'completed', error: null, report };
}
