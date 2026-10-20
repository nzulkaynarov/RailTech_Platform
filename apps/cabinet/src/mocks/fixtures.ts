import type { Schemas } from '@/api/portal';

/**
 * Фикстуры мока портального API — единственный модуль с данными (M2-CAB-01, расширен в M2-CAB-02).
 * Каждая запись типизирована схемой `erp-portal.yaml`: поле, которого нет в контракте, не скомпилируется.
 *
 * Одна компания-клиент и её сделки на «сегодня» 2026-10-14 (Asia/Tashkent):
 * - 42 — товары: запрос → КП v1 отклонено, КП v2 ждёт решения (код акцепта запрашивается, мок выдаёт `MOCK_ACCEPT_CODE`);
 * - 57 — услуга по этапам: КП просмотрено, ждёт решения;
 * - 48 — КП принято, договор ждёт подписи клиента, счёт в долларах, позиция комплектуется;
 * - 29 — договор подписан исполнителем (ждёт клиента), счёт просрочен, поставка в пути, акт возвращён;
 * - 35 — закрытая сделка: договор подписан, счёт частично оплачен, акт ждёт приёмки, одна поставка доставлена
 *   (её можно принять или оспорить), одна принята, одна оспорена;
 * - 33 — КП истекло.
 * Сценарии ошибок: неверный или не запрошенный код акцепта → 409, документ 905 сначала отвечает 202 (PDF готовится),
 * документ 909 всегда 202; сессия `empty` — компания без единого объекта (пустые состояния).
 */

/** Код акцепта КП в моке: его выдаёт мок `POST /quotes/{id}/request-code` (в ERP код уходит контакту в Telegram или на e-mail). */
export const MOCK_ACCEPT_CODE = '246810';
/** Документ, PDF которого «готовится» на первом запросе (202 + Retry-After), потом отдаётся. */
export const DOC_PREPARING_ONCE = 905;
/** Документ, PDF которого «готовится» всегда — исчерпание попыток. */
export const DOC_ALWAYS_PREPARING = 909;

/** Сделки глазами клиента: номер и название вместо внутреннего id (Q-16). */
export const deals: Record<number, Schemas['DealRef']> = {
  29: { id: 29, number: 'D-29', title: 'Насос, задвижки и манометры' },
  33: { id: 33, number: 'D-33', title: 'Кабель ВВГнг для цеха' },
  35: { id: 35, number: 'D-35', title: 'Редукторы и муфты' },
  42: { id: 42, number: 'D-42', title: 'Подшипники и ремни' },
  48: { id: 48, number: 'D-48', title: 'Электродвигатели и преобразователь' },
  57: { id: 57, number: 'D-57', title: 'Насосная станция в Чирчике' },
};

/** Сделка записи по контракту 0.3.0: только `deal {id, number, title}`, отдельного внутреннего id сделки в записи нет. */
export function dealOf(id: number): { deal: Schemas['DealRef'] } {
  return { deal: deals[id] };
}

/** Деньги суммой в копейках → строка контракта (`"123.45"`). */
function fromCents(cents: bigint, currency: string): Schemas['Money'] {
  const abs = cents < 0n ? -cents : cents;
  const amount = `${cents < 0n ? '-' : ''}${abs / 100n}.${String(abs % 100n).padStart(2, '0')}`;
  return { amount, currency };
}

/** Ставка НДС моков — 12 % (Узбекистан). */
const VAT_PERCENT = 12n;

/**
 * Итоги КП по 0.3.0: строки без НДС, `subtotal` — их сумма, `vat` — 12 % с округлением до копейки,
 * `total = subtotal + vat` (как в PDF КП).
 */
export function quoteTotals(subtotal: string, currency: string): Pick<Schemas['Quote'], 'subtotal' | 'vat' | 'total'> {
  const [whole, frac = ''] = subtotal.split('.');
  const cents = BigInt(whole) * 100n + BigInt(frac.padEnd(2, '0').slice(0, 2));
  const vat = (cents * VAT_PERCENT + 50n) / 100n;
  return { subtotal: fromCents(cents, currency), vat: fromCents(vat, currency), total: fromCents(cents + vat, currency) };
}

export const company: Schemas['Company'] = {
  id: 7,
  name: 'ООО «Тошкент Логистик»',
  inn: '305123456',
  legal_address: 'г. Ташкент, Мирзо-Улугбекский р-н, ул. Буюк Ипак Йули, 12',
  bank_details: 'р/с 20208000900123456001, АКБ «Узпромстройбанк», МФО 00440',
  language: 'ru',
};

/** Основной контакт с правом действовать (`can_act=true`). */
export const contactActor: Schemas['TeamMember'] = {
  id: 101,
  name: 'Алишер Каримов',
  email: 'a.karimov@toshlog.uz',
  phone: '+998901234567',
  has_telegram: true,
  language: 'ru',
  preferred_channel: 'both',
  can_act: true,
  is_primary: true,
  invited_at: '2026-09-01T09:00:00+05:00',
  last_login_at: '2026-10-13T18:20:00+05:00',
};

/** Коллега только с просмотром (`can_act=false`): действия скрыты, API всё равно ответит 403. */
export const contactViewer: Schemas['TeamMember'] = {
  id: 102,
  name: 'Dilnoza Yusupova',
  email: 'd.yusupova@toshlog.uz',
  phone: null,
  has_telegram: false,
  language: 'uz',
  preferred_channel: 'email',
  can_act: false,
  is_primary: false,
  invited_at: '2026-10-02T11:30:00+05:00',
  last_login_at: null,
};

const contactAccountant: Schemas['TeamMember'] = {
  id: 103,
  name: 'Нигора Рахимова',
  email: 'buh@toshlog.uz',
  phone: '+998935550011',
  has_telegram: true,
  language: 'ru',
  preferred_channel: 'telegram',
  can_act: true,
  is_primary: false,
  invited_at: '2026-09-03T10:00:00+05:00',
  last_login_at: '2026-10-10T09:12:00+05:00',
};

export const team: Schemas['TeamMember'][] = [contactActor, contactViewer, contactAccountant];

export const requests: Schemas['ClientRequest'][] = [
  {
    id: 503,
    number: 'Z-2026-0061',
    status: 'new',
    summary: 'Перчатки нитриловые, размер L — 50 упаковок',
    source: 'cabinet',
    deal: null,
    created_at: '2026-10-13T12:05:00+05:00',
  },
  {
    id: 502,
    number: 'Z-2026-0057',
    status: 'in_progress',
    summary: 'Монтаж и пусконаладка насосной станции на складе в Чирчике',
    source: 'cabinet',
    ...dealOf(57),
    created_at: '2026-10-10T16:40:00+05:00',
  },
  {
    id: 501,
    number: 'Z-2026-0042',
    status: 'quoted',
    summary: 'Подшипники 6205-2RS — 200 шт., ремни приводные SPZ 1250 — 40 шт.',
    source: 'crm',
    ...dealOf(42),
    created_at: '2026-09-28T10:15:00+05:00',
  },
  {
    id: 505,
    number: 'Z-2026-0048',
    status: 'quoted',
    summary: 'Электродвигатель АИР 100L4 — 2 шт., частотный преобразователь 4 кВт',
    source: 'erp',
    ...dealOf(48),
    created_at: '2026-09-15T09:30:00+05:00',
  },
  {
    id: 504,
    number: 'Z-2026-0035',
    status: 'closed',
    summary: 'Редукторы червячные NMRV 063 — 6 шт., муфты упругие — 12 шт.',
    source: 'crm',
    ...dealOf(35),
    created_at: '2026-08-05T14:00:00+05:00',
  },
];

const quote42: Schemas['Quote'] = {
  id: 301,
  ...dealOf(42),
  number: 'KP-2026-0042',
  version: 2,
  status: 'sent',
  ...quoteTotals('48600000.00', 'UZS'),
  valid_until: '2026-10-25',
  sent_at: '2026-10-08T14:00:00+05:00',
  public_url: 'https://cabinet.example.com/q/kp-2026-0042-v2',
  pdf_document_id: 901,
  rejected_reason: null,
  lines: [
    { line_no: 1, kind: 'section', title: 'Товары' },
    {
      line_no: 2,
      kind: 'item',
      title: 'Подшипник 6205-2RS',
      description: 'Шариковый радиальный, закрытый с двух сторон',
      quantity: '200',
      unit: 'шт',
      unit_price: { amount: '165000.00', currency: 'UZS' },
      total: { amount: '33000000.00', currency: 'UZS' },
      promised_date: '2026-11-05',
    },
    {
      line_no: 3,
      kind: 'item',
      title: 'Ремень приводной SPZ 1250',
      quantity: '40',
      unit: 'шт',
      unit_price: { amount: '390000.00', currency: 'UZS' },
      total: { amount: '15600000.00', currency: 'UZS' },
      promised_date: '2026-11-12',
    },
    { line_no: 4, kind: 'note', title: 'Доставка до склада клиента в Ташкенте включена' },
  ],
};

const quote42v1: Schemas['Quote'] = {
  ...quote42,
  id: 300,
  version: 1,
  status: 'rejected',
  ...quoteTotals('45714285.71', 'UZS'),
  valid_until: '2026-10-08',
  sent_at: '2026-10-01T11:00:00+05:00',
  public_url: 'https://cabinet.example.com/q/kp-2026-0042-v1',
  pdf_document_id: null,
  rejected_reason: 'Срок поставки ремней не устраивает',
};

const quote57: Schemas['Quote'] = {
  id: 310,
  ...dealOf(57),
  number: 'KP-2026-0057',
  version: 1,
  status: 'viewed',
  ...quoteTotals('18750000.50', 'UZS'),
  valid_until: '2026-10-31',
  sent_at: '2026-10-12T10:30:00+05:00',
  public_url: 'https://cabinet.example.com/q/kp-2026-0057-v1',
  pdf_document_id: null,
  rejected_reason: null,
  lines: [
    { line_no: 1, kind: 'section', title: 'Работы' },
    {
      line_no: 2,
      kind: 'stage',
      title: 'Этап 1. Обследование площадки и проект',
      description: 'Выезд инженера, схема подключения',
      unit_price: null,
      total: { amount: '4250000.50', currency: 'UZS' },
      promised_date: '2026-10-24',
    },
    {
      line_no: 3,
      kind: 'stage',
      title: 'Этап 2. Монтаж оборудования',
      total: { amount: '9500000.00', currency: 'UZS' },
      promised_date: '2026-11-14',
    },
    {
      line_no: 4,
      kind: 'stage',
      title: 'Этап 3. Пусконаладка и обучение персонала',
      quantity: '16',
      unit: 'ч',
      unit_price: { amount: '312500.00', currency: 'UZS' },
      total: { amount: '5000000.00', currency: 'UZS' },
      promised_date: '2026-11-21',
    },
    { line_no: 5, kind: 'note', title: 'Оплата по этапам: 30 % аванс, остаток — по актам этапов' },
  ],
};

const quote48: Schemas['Quote'] = {
  id: 320,
  ...dealOf(48),
  number: 'KP-2026-0048',
  version: 1,
  status: 'accepted',
  ...quoteTotals('12500.00', 'USD'),
  valid_until: '2026-10-01',
  sent_at: '2026-09-20T15:00:00+05:00',
  public_url: 'https://cabinet.example.com/q/kp-2026-0048-v1',
  pdf_document_id: null,
  rejected_reason: null,
  lines: [
    {
      line_no: 1,
      kind: 'item',
      title: 'Электродвигатель АИР 100L4',
      quantity: '2',
      unit: 'шт',
      unit_price: { amount: '4100.00', currency: 'USD' },
      total: { amount: '8200.00', currency: 'USD' },
      promised_date: '2026-11-01',
    },
    {
      line_no: 2,
      kind: 'item',
      title: 'Преобразователь частоты 4 кВт',
      quantity: '1',
      unit: 'шт',
      unit_price: { amount: '4300.00', currency: 'USD' },
      total: { amount: '4300.00', currency: 'USD' },
      promised_date: '2026-11-01',
    },
  ],
};

const quote33: Schemas['Quote'] = {
  id: 330,
  ...dealOf(33),
  number: 'KP-2026-0033',
  version: 1,
  status: 'expired',
  ...quoteTotals('7300000.00', 'UZS'),
  valid_until: '2026-09-10',
  sent_at: '2026-08-27T12:00:00+05:00',
  public_url: 'https://cabinet.example.com/q/kp-2026-0033-v1',
  pdf_document_id: null,
  rejected_reason: null,
  lines: [
    {
      line_no: 1,
      kind: 'item',
      title: 'Кабель ВВГнг 3×2,5',
      quantity: '500',
      unit: 'м',
      unit_price: { amount: '14600.00', currency: 'UZS' },
      total: { amount: '7300000.00', currency: 'UZS' },
      promised_date: null,
    },
  ],
};

export const quotes: Schemas['Quote'][] = [quote42, quote57, quote42v1, quote48, quote33];

export const contracts: Schemas['Contract'][] = [
  {
    id: 402,
    ...dealOf(48),
    number: 'D-2026-0048',
    status: 'sent',
    signed_by_client_at: null,
    signed_by_company_at: null,
    document_id: 905,
  },
  {
    id: 403,
    ...dealOf(29),
    number: 'D-2026-0029',
    status: 'signed_by_company',
    signed_by_client_at: null,
    signed_by_company_at: '2026-10-09T17:10:00+05:00',
    document_id: null,
  },
  {
    id: 401,
    ...dealOf(35),
    number: 'D-2026-0035',
    status: 'signed',
    signed_by_client_at: '2026-08-20T10:00:00+05:00',
    signed_by_company_at: '2026-08-20T15:30:00+05:00',
    document_id: 902,
  },
];

export const invoices: Schemas['Invoice'][] = [
  {
    id: 603,
    ...dealOf(29),
    number: 'S-2026-0124',
    status: 'issued',
    total: { amount: '9800000.00', currency: 'UZS' },
    paid: { amount: '0.00', currency: 'UZS' },
    due_date: '2026-10-07',
    document_id: null,
  },
  {
    id: 604,
    ...dealOf(48),
    number: 'S-2026-0130',
    status: 'issued',
    total: { amount: '12500.00', currency: 'USD' },
    paid: { amount: '0.00', currency: 'USD' },
    due_date: '2026-10-28',
    document_id: null,
  },
  {
    id: 601,
    ...dealOf(35),
    number: 'S-2026-0118',
    status: 'partially_paid',
    total: { amount: '27500000.00', currency: 'UZS' },
    paid: { amount: '13750000.00', currency: 'UZS' },
    due_date: '2026-10-30',
    document_id: 903,
  },
  {
    id: 602,
    ...dealOf(35),
    number: 'S-2026-0101',
    status: 'paid',
    total: { amount: '5400000.00', currency: 'UZS' },
    paid: { amount: '5400000.00', currency: 'UZS' },
    due_date: '2026-09-15',
    document_id: null,
  },
];

export const acts: Schemas['Act'][] = [
  {
    id: 701,
    ...dealOf(35),
    number: 'A-2026-0090',
    status: 'issued',
    issued_at: '2026-10-11T09:00:00+05:00',
    returned_reason: null,
    document_id: 904,
  },
  {
    id: 703,
    ...dealOf(29),
    number: 'A-2026-0084',
    status: 'returned',
    issued_at: '2026-10-03T16:00:00+05:00',
    returned_reason: 'В акте не указан серийный номер редуктора',
    document_id: null,
  },
  {
    id: 702,
    ...dealOf(29),
    number: 'A-2026-0071',
    status: 'accepted',
    issued_at: '2026-09-18T12:00:00+05:00',
    returned_reason: null,
    document_id: null,
  },
];

export const deliveries: Schemas['DeliveryLine'][] = [
  {
    id: 101,
    ...dealOf(29),
    line_no: 1,
    title: 'Насос центробежный CM 50-200',
    quantity: '2',
    unit: 'шт',
    status: 'assembling',
    eta: '2026-10-24',
    tracking: null,
    shipped_at: null,
  },
  {
    id: 102,
    ...dealOf(29),
    line_no: 2,
    title: 'Задвижка 30с41нж Ду100',
    quantity: '4',
    unit: 'шт',
    status: 'ready_to_ship',
    eta: '2026-10-16',
    tracking: null,
    shipped_at: null,
  },
  {
    id: 103,
    ...dealOf(29),
    line_no: 3,
    title: 'Манометр ДМ 02-100',
    quantity: '10',
    unit: 'шт',
    status: 'shipped',
    eta: '2026-10-15',
    tracking: 'UZP-77815230',
    shipped_at: '2026-10-12T11:00:00+05:00',
  },
  {
    id: 104,
    ...dealOf(48),
    line_no: 1,
    title: 'Электродвигатель АИР 100L4',
    quantity: '2',
    unit: 'шт',
    status: 'assembling',
    eta: null,
    tracking: null,
    shipped_at: null,
  },
  {
    id: 105,
    ...dealOf(35),
    line_no: 1,
    title: 'Редуктор червячный NMRV 063',
    quantity: '6',
    unit: 'шт',
    status: 'delivered',
    eta: '2026-09-25',
    tracking: 'UZP-77812044',
    shipped_at: '2026-09-21T08:00:00+05:00',
  },
  {
    id: 106,
    ...dealOf(35),
    line_no: 2,
    title: 'Муфта упругая МУВП-3',
    quantity: '12',
    unit: 'шт',
    status: 'in_transit',
    eta: '2026-10-20',
    tracking: null,
    shipped_at: null,
  },
  {
    id: 107,
    ...dealOf(35),
    line_no: 3,
    title: 'Втулка резиновая для МУВП-3',
    quantity: '24',
    unit: 'шт',
    status: 'accepted',
    eta: '2026-09-25',
    tracking: 'UZP-77812044',
    shipped_at: '2026-09-21T08:00:00+05:00',
    accepted_at: '2026-09-27T10:15:00+05:00',
    remark: null,
  },
  {
    id: 108,
    ...dealOf(35),
    line_no: 4,
    title: 'Масло редукторное ТАД-17и, 20 л',
    quantity: '3',
    unit: 'шт',
    status: 'disputed',
    eta: '2026-09-25',
    tracking: 'UZP-77812044',
    shipped_at: '2026-09-21T08:00:00+05:00',
    accepted_at: '2026-09-27T10:20:00+05:00',
    remark: 'У двух канистр нарушена пломба',
  },
];

export const documents: Schemas['Document'][] = [
  { id: 905, ...dealOf(48), kind: 'contract', number: 'D-2026-0048', date: '2026-10-02', title: 'Договор поставки № D-2026-0048', file_name: 'D-2026-0048.pdf', size_bytes: 398336 },
  { id: 904, ...dealOf(35), kind: 'act', number: 'A-2026-0090', date: '2026-10-11', title: 'Акт № A-2026-0090', file_name: 'A-2026-0090.pdf', size_bytes: 88064 },
  { id: 901, ...dealOf(42), kind: 'quote', number: 'KP-2026-0042', date: '2026-10-08', title: 'КП № KP-2026-0042, версия 2', file_name: 'KP-2026-0042-v2.pdf', size_bytes: 184320 },
  { id: 903, ...dealOf(35), kind: 'invoice', number: 'S-2026-0118', date: '2026-10-01', title: 'Счёт № S-2026-0118', file_name: 'S-2026-0118.pdf', size_bytes: 96256 },
  { id: 906, ...dealOf(35), kind: 'waybill', number: 'TN-2026-0412', date: '2026-09-21', title: 'Товарная накладная № TN-2026-0412', file_name: 'TN-2026-0412.pdf', size_bytes: 120832 },
  { id: 907, ...dealOf(35), kind: 'receipt', number: 'PP-2026-1187', date: '2026-09-12', title: 'Платёжное поручение № PP-2026-1187', file_name: 'PP-2026-1187.pdf', size_bytes: 51200 },
  { id: 902, ...dealOf(35), kind: 'contract', number: 'D-2026-0035', date: '2026-08-20', title: 'Договор поставки № D-2026-0035', file_name: 'D-2026-0035.pdf', size_bytes: 412672 },
  { id: 909, deal: null, kind: 'other', number: 'AS-2026-09', date: '2026-10-01', title: 'Акт сверки за сентябрь 2026', file_name: 'AS-2026-09.pdf', size_bytes: 64512 },
  { id: 908, deal: null, kind: 'other', number: 'SR-2026-031', date: '2026-07-14', title: 'Сертификат соответствия на подшипники', file_name: 'SR-2026-031.pdf', size_bytes: 1572864 },
];

const goods = (
  id: number,
  name: string,
  category: string,
  unit: string,
  price: string | null,
  availability: Schemas['Availability'],
  leadTimeDays: number | null,
): Schemas['CatalogItem'] => ({
  id,
  kind: 'goods',
  name,
  unit,
  category,
  price: price === null ? null : { amount: price, currency: 'UZS' },
  availability,
  lead_time_days: leadTimeDays,
  images: [],
  attributes: [],
});

export const catalog: Schemas['CatalogItem'][] = [
  {
    id: 1001,
    kind: 'goods',
    name: 'Подшипник 6205-2RS',
    description: 'Шариковый радиальный, закрытый с двух сторон. Подходит для электродвигателей и насосов.',
    unit: 'шт',
    category: 'Подшипники',
    price: { amount: '165000.00', currency: 'UZS' },
    availability: 'in_stock',
    lead_time_days: 2,
    images: [],
    attributes: [
      { name: 'Внутренний диаметр', value: '25 мм' },
      { name: 'Наружный диаметр', value: '52 мм' },
      { name: 'Ширина', value: '15 мм' },
    ],
  },
  {
    id: 1002,
    kind: 'goods',
    name: 'Ремень приводной SPZ 1250',
    description: 'Клиновой узкого профиля',
    unit: 'шт',
    category: 'Ремни',
    price: { amount: '390000.00', currency: 'UZS' },
    availability: 'on_order',
    lead_time_days: 14,
    images: [],
    attributes: [{ name: 'Расчётная длина', value: '1250 мм' }],
  },
  {
    id: 1003,
    kind: 'service',
    name: 'Пусконаладка насосного оборудования',
    description: 'Выезд инженера, проверка подключения, пробный пуск, обучение персонала',
    unit: 'усл.',
    category: 'Услуги',
    price: null,
    availability: 'expected',
    lead_time_days: null,
    images: [],
    attributes: [],
  },
  {
    id: 1004,
    kind: 'service',
    name: 'Монтаж электродвигателя до 15 кВт',
    unit: 'усл.',
    category: 'Услуги',
    price: { amount: '1200000.00', currency: 'UZS' },
    availability: 'in_stock',
    lead_time_days: 3,
    images: [],
    attributes: [],
  },
  goods(1005, 'Подшипник 6305-2Z', 'Подшипники', 'шт', '210000.00', 'in_stock', 2),
  goods(1006, 'Подшипник 6206-2RS', 'Подшипники', 'шт', '189000.00', 'in_stock', 2),
  goods(1007, 'Подшипник роликовый 32210', 'Подшипники', 'шт', null, 'on_order', 21),
  goods(1008, 'Подшипник 6008-ZZ', 'Подшипники', 'шт', '98000.00', 'expected', 10),
  goods(1009, 'Ремень приводной SPA 1500', 'Ремни', 'шт', '420000.00', 'in_stock', 2),
  goods(1010, 'Ремень зубчатый HTD 8M-1200', 'Ремни', 'шт', '615000.00', 'on_order', 14),
  goods(1011, 'Болт М12×60 оцинкованный', 'Крепёж', 'шт', '3200.00', 'in_stock', 1),
  goods(1012, 'Гайка М12 оцинкованная', 'Крепёж', 'шт', '900.00', 'in_stock', 1),
  goods(1013, 'Анкер клиновой 10×100', 'Крепёж', 'шт', '5400.00', 'in_stock', 1),
  goods(1014, 'Шайба пружинная 12', 'Крепёж', 'шт', '350.00', 'expected', 7),
  goods(1015, 'Кабель ВВГнг 3×2,5', 'Электрика', 'м', '14600.00', 'in_stock', 2),
  goods(1016, 'Автоматический выключатель 3P 25A', 'Электрика', 'шт', '185000.00', 'in_stock', 2),
  goods(1017, 'Контактор 32A 220V', 'Электрика', 'шт', '348000.00', 'on_order', 10),
  goods(1018, 'Преобразователь частоты 4 кВт', 'Электрика', 'шт', null, 'on_order', 30),
  goods(1019, 'Перчатки нитриловые, размер L', 'Средства защиты', 'уп.', '78000.00', 'in_stock', 0),
  goods(1020, 'Очки защитные открытые', 'Средства защиты', 'шт', '42000.00', 'in_stock', 1),
  goods(1021, 'Каска защитная', 'Средства защиты', 'шт', '96000.00', 'expected', 5),
  goods(1022, 'Манометр ДМ 02-100', 'Приборы', 'шт', '265000.00', 'in_stock', 3),
  goods(1023, 'Термометр биметаллический ТБ-63', 'Приборы', 'шт', '134000.00', 'on_order', 12),
  goods(1024, 'Задвижка 30с41нж Ду100', 'Арматура', 'шт', null, 'on_order', 25),
];

export function meFor(contact: Schemas['TeamMember'], authMethod: Schemas['Me']['auth_method']): Schemas['Me'] {
  return { contact, company, can_act: contact.can_act, auth_method: authMethod };
}
