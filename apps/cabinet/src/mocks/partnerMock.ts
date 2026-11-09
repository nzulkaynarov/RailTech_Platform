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

const DOCUMENTS: Record<number, Schemas['PartnerProductDocument'][]> = {
  9001: [
    {
      id: 7001,
      kind: 'certificate',
      kind_name: 'Сертификат соответствия',
      title: 'Сертификат соответствия ГОСТ 7798-70',
      number: 'ЕАЭС RU С-RU.АЯ46.В.00001/26',
      issued_by: 'Орган по сертификации',
      issued_at: '2026-01-15',
      valid_until: '2029-01-14',
      original_name: 'certificate-brake-pads.pdf',
      size_bytes: 524288,
      status: 'approved',
      can_delete: false,
      created_at: '2026-02-01T12:00:00+05:00',
    },
    {
      id: 7002,
      kind: 'passport',
      kind_name: 'Паспорт изделия',
      title: 'Протокол испытаний колодок',
      number: 'ПИ-2026/14',
      issued_by: 'Испытательная лаборатория',
      issued_at: '2026-03-10',
      valid_until: null,
      original_name: 'test-protocol.pdf',
      size_bytes: 262144,
      status: 'pending',
      can_delete: true,
      created_at: '2026-10-13T12:00:00+05:00',
    },
  ],
};

export function documentsOf(productId: number): Schemas['PartnerProductDocument'][] {
  return DOCUMENTS[productId] ?? [];
}

export function addDocument(
  productId: number,
  data: {
    kind?: string;
    title: string;
    number?: string;
    issued_by?: string;
    issued_at?: string | null;
    valid_until?: string | null;
    file_name?: string;
    size_bytes?: number;
  },
): Schemas['PartnerProductDocument'] {
  const list = DOCUMENTS[productId] ?? (DOCUMENTS[productId] = []);
  const nextId = 7000 + list.length + 1;
  const doc: Schemas['PartnerProductDocument'] = {
    id: nextId,
    kind: data.kind || 'certificate',
    kind_name: data.kind === 'passport' ? 'Паспорт изделия' : 'Сертификат соответствия',
    title: data.title,
    number: data.number || '',
    issued_by: data.issued_by || '',
    issued_at: data.issued_at || null,
    valid_until: data.valid_until || null,
    original_name: data.file_name || `${data.title}.pdf`,
    size_bytes: data.size_bytes || 102400,
    // Как в ERP: присланное партнёром ждёт сотрудника и клиенту не видно (FX-2)
    status: 'pending',
    can_delete: true,
    created_at: new Date().toISOString(),
  };
  list.push(doc);
  return doc;
}

export function deleteDocument(productId: number, docId: number): boolean {
  const list = DOCUMENTS[productId];
  if (!list) return false;
  const idx = list.findIndex((d) => d.id === docId);
  if (idx === -1) return false;
  list.splice(idx, 1);
  return true;
}

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
  if (product.status === 'matched') return { ...product, description: '', hs_code: '', uom: null, missing: [], history: [], documents: [] };
  return {
    ...product,
    description: product.is_own ? `Описание: ${product.name}.` : '',
    hs_code: product.is_own ? '8708301009' : '',
    uom: 'шт',
    missing: MISSING[product.id] ?? [],
    history,
    documents: documentsOf(product.id),
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

// --- Заказы на поставку (PO, ASN) и запросы цен (RFQ) партнёра (K2-orders) ---

export function partnerOrders(): Schemas['PartnerOrderDetail'][] {
  return [
    {
      id: 8001,
      number: 'PO-2026-0041',
      status: 'sent',
      expected_date: '2026-11-20',
      total_amount: '1505000.00',
      currency: 'UZS',
      note: 'Просьба отгрузить одной партией на склад Ташкент.',
      date_change: null,
      shipment_notices: [],
      sent_at: '2026-11-01T10:05:00+05:00',
      confirmed_at: null,
      received_at: null,
      cancelled_at: null,
      created_at: '2026-11-01T10:00:00+05:00',
      lines: [
        {
          id: 8101,
          position: 1,
          product_id: 9001,
          name: 'Тормозная колодка композитная',
          article: 'AQ-9001',
          quantity: 10,
          received_quantity: 0,
          unit: 'шт',
          unit_price: '150500.00',
          total_price: '1505000.00',
        },
      ],
      logs: [
        {
          id: 8201,
          kind: 'sent',
          created_at: '2026-11-01T10:05:00+05:00',
        },
      ],
      receipts: [],
    },
    {
      id: 8002,
      number: 'PO-2026-0042',
      status: 'confirmed',
      expected_date: '2026-11-25',
      total_amount: '420000.00',
      currency: 'UZS',
      note: '',
      date_change: null,
      shipment_notices: [],
      sent_at: '2026-11-02T09:10:00+05:00',
      confirmed_at: '2026-11-02T14:30:00+05:00',
      received_at: null,
      cancelled_at: null,
      created_at: '2026-11-02T09:00:00+05:00',
      lines: [
        {
          id: 8102,
          position: 1,
          product_id: 9002,
          name: 'Подшипник 6205-2RS',
          article: '6205-2RS',
          quantity: 100,
          received_quantity: 50,
          unit: 'шт',
          unit_price: '4200.00',
          total_price: '420000.00',
        },
      ],
      logs: [
        {
          id: 8202,
          kind: 'confirmed',
          created_at: '2026-11-02T14:30:00+05:00',
        },
      ],
      receipts: [
        {
          id: 8301,
          supplier_doc: 'ТН-1002 от 05.11.2026',
          received_at: '2026-11-06T15:00:00+05:00',
          lines: [
            {
              id: 8401,
              order_line_id: 8102,
              name: 'Подшипник 6205-2RS',
              article: '6205-2RS',
              quantity: 50,
              unit: 'шт',
              warehouse_name: 'Центральный склад Ташкент',
              conformity_doc_number: 'ЕАЭС RU С-RU.АЯ46.В.00001/26',
              conformity_doc_valid_until: '2029-01-14',
            },
          ],
        },
      ],
    },
  ];
}

export function orderStatusCounts(items: Schemas['PartnerOrderDetail'][]): Schemas['PartnerOrderStatusCounts'] {
  const count = (status: Schemas['PartnerOrderStatus']) => items.filter((item) => item.status === status).length;
  return {
    all: items.length,
    sent: count('sent'),
    confirmed: count('confirmed'),
    received: count('received'),
    cancelled: count('cancelled'),
  };
}

export function partnerPriceRequests(): Schemas['PartnerPriceRequestDetail'][] {
  return [
    {
      id: 8501,
      status: 'sent',
      subject: 'Запрос цен на тормозные колодки и втулки (Q4)',
      requested_at: '2026-11-05T11:00:00+05:00',
      answered_at: null,
      note: 'Укажите срок поставки до Ташкента (FCA/DAP).',
      answer_note: '',
      answer_currency: null,
      lines: [
        {
          id: 8601,
          name: 'Тормозная колодка композитная',
          article: 'AQ-9001',
          quantity: 50,
          unit: 'шт',
          answer_price: null,
        },
        {
          id: 8602,
          name: 'Втулка резиновая',
          article: 'AQ-9004',
          quantity: 200,
          unit: 'шт',
          answer_price: null,
        },
      ],
    },
  ];
}

export function rfqStatusCounts(items: Schemas['PartnerPriceRequestDetail'][]): Schemas['PartnerPriceRequestStatusCounts'] {
  const count = (status: Schemas['PartnerPriceRequestStatus']) => items.filter((item) => item.status === status).length;
  return {
    all: items.length,
    sent: count('sent'),
    answered: count('answered'),
  };
}

export function partnerFinanceSummary(
  orders: Schemas['PartnerOrderDetail'][] = partnerOrders(),
  page = 1,
  pageSize = 20,
): Schemas['PartnerFinanceSummary'] {
  const currencyMap = new Map<
    string,
    { currency: string; ordered: number; received: number; in_transit: number; count: number }
  >();

  const settlements: Schemas['PartnerSettlementLine'][] = orders.filter((order) => order.status !== 'draft').map((order) => {
    const orderedAmount = order.lines.reduce(
      (sum, line) => sum + Number(line.unit_price || 0) * line.quantity,
      0,
    );
    const receivedAmount = order.lines.reduce(
      (sum, line) => sum + Number(line.unit_price || 0) * (line.received_quantity || 0),
      0,
    );
    const inTransitAmount =
      order.status === 'confirmed' && order.shipment_notices.length > 0
        ? order.lines.reduce(
            (sum, line) =>
              sum + Number(line.unit_price || 0) * Math.max(0, line.quantity - (line.received_quantity || 0)),
            0,
          )
        : 0;

    const curr = order.currency;
    if (order.status !== 'cancelled') {
      const entry = currencyMap.get(curr) || {
        currency: curr,
        ordered: 0,
        received: 0,
        in_transit: 0,
        count: 0,
      };
      entry.ordered += orderedAmount;
      entry.received += receivedAmount;
      entry.in_transit += inTransitAmount;
      entry.count += 1;
      currencyMap.set(curr, entry);
    }

    return {
      order_id: order.id,
      order_number: order.number,
      order_date: order.created_at,
      status: order.status,
      currency: order.currency,
      ordered_amount: orderedAmount.toFixed(2),
      received_amount: receivedAmount.toFixed(2),
      in_transit_amount: inTransitAmount.toFixed(2),
      receipts_count: order.receipts.length,
    };
  });

  const balances: Schemas['PartnerFinanceBalance'][] = Array.from(currencyMap.values()).map((c) => ({
    currency: c.currency,
    ordered_total: c.ordered.toFixed(2),
    received_total: c.received.toFixed(2),
    in_transit_total: c.in_transit.toFixed(2),
    orders_count: c.count,
  }));

  const scorecard: Schemas['PartnerFinanceScorecard'] = {
    otif_rate: 96.5,
    otif_orders_count: orders.filter((o) => o.status === 'received').length,
    rfq_response_rate: 90.0,
    rfq_avg_response_hours: 18.5,
    price_freshness_rate: 95.0,
    total_rfqs_count: 5,
    active_offers_count: 24,
  };

  return {
    balances,
    scorecard,
    settlements: settlements.slice((page - 1) * pageSize, page * pageSize),
    settlements_total: settlements.length,
    page,
    page_size: pageSize,
  };
}
