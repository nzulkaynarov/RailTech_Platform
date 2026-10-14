import type { Schemas } from '@/api/portal';

/**
 * Фикстуры мока портального API — единственный модуль с данными (M2-CAB-01). Каждая запись
 * типизирована схемой `erp-portal.yaml`: поле, которого нет в контракте, не скомпилируется.
 * Данные — одна компания-клиент со сделкой 42 «от запроса до поставки»; используют dev-мок
 * (`VITE_PORTAL_MOCK=1`) и тесты (msw/node).
 */

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

export const team: Schemas['TeamMember'][] = [contactActor, contactViewer];

export const requests: Schemas['ClientRequest'][] = [
  {
    id: 501,
    number: 'Z-2026-0042',
    status: 'quoted',
    summary: 'Подшипники 6205-2RS — 200 шт., ремни приводные SPZ 1250 — 40 шт.',
    source: 'crm',
    deal_id: 42,
    created_at: '2026-09-28T10:15:00+05:00',
  },
  {
    id: 502,
    number: 'Z-2026-0057',
    status: 'in_progress',
    summary: 'Монтаж и пусконаладка насосной станции на складе в Чирчике',
    source: 'cabinet',
    deal_id: 57,
    created_at: '2026-10-10T16:40:00+05:00',
  },
  {
    id: 503,
    number: 'Z-2026-0061',
    status: 'new',
    summary: 'Перчатки нитриловые, размер L — 50 упаковок',
    source: 'cabinet',
    deal_id: null,
    created_at: '2026-10-13T12:05:00+05:00',
  },
];

const quote42: Schemas['Quote'] = {
  id: 301,
  deal_id: 42,
  number: 'KP-2026-0042',
  version: 2,
  status: 'sent',
  total: { amount: '48600000.00', currency: 'UZS' },
  valid_until: '2026-10-25',
  sent_at: '2026-10-08T14:00:00+05:00',
  public_url: 'https://cabinet.railtech.uz/q/kp-2026-0042-v2',
  pdf_document_id: 901,
  rejected_reason: null,
  lines: [
    { line_no: 1, kind: 'section', title: 'Товары' },
    {
      line_no: 2,
      kind: 'item',
      title: 'Подшипник 6205-2RS',
      description: 'SKF, оригинал',
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
  total: { amount: '51200000.00', currency: 'UZS' },
  sent_at: '2026-10-01T11:00:00+05:00',
  public_url: 'https://cabinet.railtech.uz/q/kp-2026-0042-v1',
  pdf_document_id: null,
  rejected_reason: 'Срок поставки ремней не устраивает',
};

export const quotes: Schemas['Quote'][] = [quote42, quote42v1];

export const contracts: Schemas['Contract'][] = [
  {
    id: 401,
    deal_id: 35,
    number: 'D-2026-0035',
    status: 'signed',
    signed_by_client_at: '2026-08-20T10:00:00+05:00',
    signed_by_company_at: '2026-08-20T15:30:00+05:00',
    document_id: 902,
  },
];

export const invoices: Schemas['Invoice'][] = [
  {
    id: 601,
    deal_id: 35,
    number: 'S-2026-0118',
    status: 'partially_paid',
    total: { amount: '27500000.00', currency: 'UZS' },
    paid: { amount: '13750000.00', currency: 'UZS' },
    due_date: '2026-10-30',
    document_id: 903,
  },
];

export const acts: Schemas['Act'][] = [
  {
    id: 701,
    deal_id: 35,
    number: 'A-2026-0090',
    status: 'issued',
    issued_at: '2026-10-11T09:00:00+05:00',
    returned_reason: null,
    document_id: 904,
  },
];

export const deliveries: Schemas['DeliveryLine'][] = [
  {
    deal_id: 35,
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
    deal_id: 35,
    line_no: 2,
    title: 'Муфта упругая МУВП-3',
    quantity: '12',
    unit: 'шт',
    status: 'in_transit',
    eta: '2026-10-20',
    tracking: null,
    shipped_at: null,
  },
];

export const documents: Schemas['Document'][] = [
  { id: 901, deal_id: 42, kind: 'quote', number: 'KP-2026-0042', date: '2026-10-08', title: 'КП № KP-2026-0042, версия 2', file_name: 'KP-2026-0042-v2.pdf', size_bytes: 184320 },
  { id: 902, deal_id: 35, kind: 'contract', number: 'D-2026-0035', date: '2026-08-20', title: 'Договор поставки № D-2026-0035', file_name: 'D-2026-0035.pdf', size_bytes: 412672 },
  { id: 903, deal_id: 35, kind: 'invoice', number: 'S-2026-0118', date: '2026-10-01', title: 'Счёт № S-2026-0118', file_name: 'S-2026-0118.pdf', size_bytes: 96256 },
  { id: 904, deal_id: 35, kind: 'act', number: 'A-2026-0090', date: '2026-10-11', title: 'Акт № A-2026-0090', file_name: 'A-2026-0090.pdf', size_bytes: 88064 },
];

export const catalog: Schemas['CatalogItem'][] = [
  {
    id: 1001,
    kind: 'goods',
    name: 'Подшипник 6205-2RS',
    description: 'Шариковый радиальный, закрытый с двух сторон',
    unit: 'шт',
    category: 'Подшипники',
    price: { amount: '165000.00', currency: 'UZS' },
    availability: 'in_stock',
    lead_time_days: 2,
    images: [],
    attributes: [
      { name: 'Внутренний диаметр', value: '25 мм' },
      { name: 'Наружный диаметр', value: '52 мм' },
    ],
  },
  {
    id: 1002,
    kind: 'goods',
    name: 'Ремень приводной SPZ 1250',
    unit: 'шт',
    category: 'Ремни',
    price: { amount: '390000.00', currency: 'UZS' },
    availability: 'on_order',
    lead_time_days: 14,
    images: [],
    attributes: [],
  },
  {
    id: 1003,
    kind: 'service',
    name: 'Пусконаладка насосного оборудования',
    unit: 'усл.',
    category: 'Услуги',
    price: null,
    availability: 'expected',
    lead_time_days: null,
    images: [],
    attributes: [],
  },
];

export function meFor(contact: Schemas['TeamMember'], authMethod: Schemas['Me']['auth_method']): Schemas['Me'] {
  return { contact, company, can_act: contact.can_act, auth_method: authMethod };
}
