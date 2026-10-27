import type {
  BrandProfile,
  CatalogCategory,
  CategoryRequest,
  ChargeTemplate,
  ChargeType,
  CompanyProfile,
  DocumentTemplate,
  EmailTemplate,
  FxRate,
  FxRateJournalEntry,
  NumberingScheme,
  PlatformSettings,
  QuoteDefaults,
  ReferenceItem,
  ReferenceKind,
} from "../../shared/api/generated/model";

/**
 * Настройки своей компании для MSW (Admin · Компания, W13-A3). Всё вымышлено: реквизиты, ИНН, банк, адреса — домен
 * `.example` и заведомо ненастоящие номера (репозиторий публичный). Состояние лежит в `localStorage` страницы (как сессия
 * и роли мока): правки в интерфейсе переживают перезагрузку; без хранилища — копия в памяти.
 */
const KEY = "rt-pf-mock-company-v2"; // v2: добавлен курс USD→UZS (`fx`)
const SEEDED_AT = "2026-10-20T06:00:00.000Z";

/** Квадрат-заглушка вместо загруженного файла (мок не читает содержимое). */
export const MOCK_LOGO =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96"><rect width="96" height="96" rx="12" fill="#1668dc"/><path d="M24 64 L48 28 L72 64 Z" fill="#fff"/></svg>',
  );

export type MockQuoteDefaults = Required<QuoteDefaults>;

export interface CompanyMock {
  company: CompanyProfile;
  brand: BrandProfile;
  numbering: NumberingScheme;
  quote: MockQuoteDefaults;
  chargeTypes: ChargeType[];
  charges: ChargeTemplate[];
  docTemplates: DocumentTemplate[];
  emailTemplates: EmailTemplate[];
  reference: Record<ReferenceKind, ReferenceItem[]>;
  categories: CatalogCategory[];
  requests: CategoryRequest[];
  platform: PlatformSettings;
  /** Курс USD→UZS: текущий и журнал ручных вводов (новые первыми) */
  fx: { current: FxRate | null; journal: FxRateJournalEntry[] };
  /** Следующий свободный id для новых строк */
  nextId: number;
}

const item = (
  id: number,
  code: string,
  name: string,
  extra: Partial<ReferenceItem> = {},
): ReferenceItem => ({
  id: String(id),
  code,
  name,
  sort_order: id,
  is_active: true,
  ...extra,
});

function seed(): CompanyMock {
  return {
    company: {
      name: "ООО «Демо Рейл»",
      inn: "123456789",
      bank_account: "20208000900000000001",
      mfo: "00001",
      legal_address: "г. Демоград, ул. Вымышленная, д. 1",
      phone: "+998 00 000 00 00",
      contact_person: "Демо Директоров",
      website: "https://demo-rail.example",
      email: "info@demo-rail.example",
      country: 1,
      has_iso9001: true,
      logo_url: null,
    },
    brand: {
      legal_name: "ООО «Демо Рейл»",
      inn: "123456789",
      legal_address: "",
      bank_details: "",
      signatory_name: "Демо Директоров",
      signatory_position: "Директор",
      footer_text: "ООО «Демо Рейл» · info@demo-rail.example",
      accent_color: "#1668dc",
      secondary_color: "#595959",
      cover_letter_text: "Направляем коммерческое предложение на поставку запрошенной продукции.",
      contract_acceptance_text: "",
      contract_liability_text: "",
      contract_extra_terms_text: "",
      act_closing_text: "",
      layout_preset: "boxed",
      font_family: "sans",
      show_cover_letter: true,
      show_bank_in_header: false,
      use_company_defaults: true,
      show_logo: true,
      show_lead_time: true,
      show_fx_note: false,
      logo_url: null,
      inherited: {
        legal_address: "г. Демоград, ул. Вымышленная, д. 1",
        bank_details: "р/с 20208000900000000001, МФО 00001",
      },
    },
    numbering: {
      pattern: "{prefix}{type}-{YYYY}-{seq}",
      padding: 5,
      reset_period: "yearly",
      start_value: 0,
      prefix: "DEMO",
      is_effective: true,
      type_labels: { quote: "КП", contract: "ДОГ", invoice: "СЧ", act: "АКТ", letter: "ПИС" },
    },
    quote: {
      default_cost_currency: "USD",
      default_delivery_basis: "FCA",
      default_vat_rate: "12.00",
      default_margin_percent: "18.00",
      min_margin_percent: "5.00",
      target_margin_percent: "20.00",
      default_offer_validity_days: 14,
      payment_terms_days: 10,
      default_payment_terms: "Предоплата 30%, остаток в течение 10 дней после поставки",
      default_warranty_months: 12,
      catalog_price_visibility: "on_request",
      catalog_publish_threshold: 70,
      fx_rate_max_age_days: 7,
    },
    chargeTypes: [
      { id: "1", code: "FREIGHT", name: "Фрахт" },
      { id: "2", code: "INSURANCE", name: "Страхование груза" },
      { id: "3", code: "CUSTOMS", name: "Таможенное оформление" },
      { id: "4", code: "INLAND", name: "Доставка до склада" },
    ],
    charges: [
      {
        id: "1",
        delivery_basis: "FCA",
        delivery_basis_name: "FCA — франко-перевозчик",
        charge_type: "FREIGHT",
        charge_type_name: "Фрахт",
        default_amount: "1500.00",
        default_rate_percent: null,
        is_deduction: false,
        sort_order: 1,
        is_active: true,
      },
      {
        id: "2",
        delivery_basis: "FCA",
        delivery_basis_name: "FCA — франко-перевозчик",
        charge_type: "INSURANCE",
        charge_type_name: "Страхование груза",
        default_amount: "0.00",
        default_rate_percent: "0.30",
        is_deduction: false,
        sort_order: 2,
        is_active: true,
      },
      {
        id: "3",
        delivery_basis: "DAP",
        delivery_basis_name: "DAP — поставка в месте назначения",
        charge_type: "CUSTOMS",
        charge_type_name: "Таможенное оформление",
        default_amount: "400.00",
        default_rate_percent: null,
        is_deduction: false,
        sort_order: 1,
        is_active: true,
      },
    ],
    docTemplates: [
      {
        id: "1",
        name: "Образец: договор поставки",
        kind: "contract",
        kind_name: "Договор",
        body_html:
          "<h2>Договор поставки</h2><p>Покупатель: {{buyer_name}}</p><p>Сумма: {{total}}</p>{{doc.spec_table}}{{doc.totals}}{{doc.requisites_and_signatures}}",
        is_sample: true,
        is_owned: false,
        is_active: true,
        placeholders_used: ["buyer_name", "total"],
        updated_at: SEEDED_AT,
      },
      {
        id: "2",
        name: "Договор поставки (наш)",
        kind: "contract",
        kind_name: "Договор",
        body_html:
          "<h2>Договор поставки</h2><p>Покупатель: {{buyer_name}}</p><p>Срок: {{delivery_term}}</p>{{doc.spec_table}}{{doc.totals}}{{doc.requisites_and_signatures}}",
        is_sample: false,
        is_owned: true,
        is_active: true,
        placeholders_used: ["buyer_name", "delivery_term"],
        updated_at: SEEDED_AT,
      },
      {
        id: "3",
        name: "Акт приёмки",
        kind: "act",
        kind_name: "Акт",
        body_html: "<h2>Акт</h2><p>Принято от {{seller_name}}</p>",
        is_sample: false,
        is_owned: true,
        is_active: false,
        placeholders_used: ["seller_name"],
        updated_at: SEEDED_AT,
      },
    ],
    emailTemplates: [
      {
        id: "1",
        key: "invoice_issued",
        language: "ru",
        subject: "Счёт {{number}} на оплату",
        html_body: "<p>Выставлен счёт {{number}} на сумму {{amount}}.</p>",
        text_body: "Выставлен счёт {{number}} на сумму {{amount}}.",
        available_variables: "number, amount, due_date",
        is_active: true,
        updated_at: SEEDED_AT,
        updated_by: "admin@demo.example",
      },
      {
        id: "2",
        key: "quote_sent",
        language: "ru",
        subject: "Коммерческое предложение {{number}}",
        html_body: "<p>Направляем КП {{number}}.</p>",
        text_body: "Направляем КП {{number}}.",
        available_variables: "number, valid_until",
        is_active: false,
        updated_at: SEEDED_AT,
      },
    ],
    reference: {
      countries: [
        item(1, "UZ", "Узбекистан", {
          alpha2: "UZ",
          alpha3: "UZB",
          iso_numeric: "860",
          vat_rate: "12.00",
        }),
        item(2, "KZ", "Казахстан", {
          alpha2: "KZ",
          alpha3: "KAZ",
          iso_numeric: "398",
          vat_rate: "12.00",
        }),
        item(3, "CN", "Китай", { alpha2: "CN", alpha3: "CHN", iso_numeric: "156", vat_rate: null }),
      ],
      currencies: [
        item(1, "UZS", "Узбекский сум", { symbol: "сум" }),
        item(2, "USD", "Доллар США", { symbol: "$" }),
        item(3, "EUR", "Евро", { symbol: "€" }),
        item(4, "RUB", "Российский рубль", { symbol: "₽", is_active: false }),
      ],
      units: [
        item(1, "PCS", "шт."),
        item(2, "KG", "кг"),
        item(3, "M", "м"),
        item(4, "SET", "компл."),
      ],
      "delivery-basis": [
        item(1, "EXW", "EXW — франко-завод", {
          description: "Продавец передаёт товар на своём складе",
          seller_pays_freight: false,
          seller_pays_insurance: false,
          seller_pays_import: false,
          seller_pays_delivery: false,
        }),
        item(2, "FCA", "FCA — франко-перевозчик", {
          description: "Продавец передаёт товар перевозчику покупателя",
          seller_pays_freight: false,
          seller_pays_insurance: false,
          seller_pays_import: false,
          seller_pays_delivery: false,
        }),
        item(3, "DAP", "DAP — поставка в месте назначения", {
          description: "Продавец доставляет товар до места назначения",
          seller_pays_freight: true,
          seller_pays_insurance: true,
          seller_pays_import: false,
          seller_pays_delivery: true,
        }),
      ],
    },
    categories: [
      { id: "1", name: "Рельсы и скрепления", parent_id: null },
      { id: "2", name: "Крепёж", parent_id: "1" },
      { id: "3", name: "Подвижной состав", parent_id: null },
      { id: "4", name: "Запчасти вагонов", parent_id: "3" },
      { id: "5", name: "Электрооборудование", parent_id: null },
    ],
    requests: [
      {
        id: "1",
        proposed_name: "Стрелочные переводы",
        parent_name: "Рельсы и скрепления",
        justification: "Нужна отдельная категория для нового каталога стрелочных переводов",
        status: "pending",
        company_name: "ООО «Демо Рейл»",
        requested_by: "manager@demo.example",
        created_at: "2026-10-24T08:30:00.000Z",
      },
      {
        id: "2",
        proposed_name: "Тормозные колодки",
        justification: "Часто запрашивают клиенты",
        status: "pending",
        company_name: "ООО «Демо Рейл»",
        requested_by: "supply@demo.example",
        created_at: "2026-10-25T10:00:00.000Z",
      },
      {
        id: "3",
        proposed_name: "Запчасти вагонов",
        status: "approved",
        company_name: "ООО «Демо Рейл»",
        requested_by: "engineer@demo.example",
        resulting_category_id: "4",
        resulting_category_name: "Запчасти вагонов",
        reviewed_at: "2026-10-22T09:00:00.000Z",
        created_at: "2026-10-21T08:00:00.000Z",
      },
    ],
    platform: { vat_rate: "12.00", exchange_rate_usd_uzs: "12650.5000", updated_at: SEEDED_AT },
    fx: {
      current: { rate_to_uzs: "12650.5", rate_date: "2026-10-26", source: "auto" },
      journal: [
        {
          id: "2",
          kind: "auto_skipped",
          rate_date: "2026-10-25",
          rate_to_uzs: "12610",
          previous_rate_to_uzs: "12600",
          previous_source: "manual",
          entered_by: null,
          entered_at: "2026-10-26T04:30:00.000Z",
        },
        {
          id: "1",
          kind: "manual",
          rate_date: "2026-10-25",
          rate_to_uzs: "12600",
          previous_rate_to_uzs: null,
          previous_source: null,
          entered_by: "Демо Директоров",
          entered_at: "2026-10-25T07:15:00.000Z",
        },
      ],
    },
    nextId: 100,
  };
}

let memory: CompanyMock | null = null;

export function readCompanyMock(): CompanyMock {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as CompanyMock;
    const fresh = seed();
    window.localStorage.setItem(KEY, JSON.stringify(fresh));
    return fresh;
  } catch {
    memory ??= seed();
    return memory;
  }
}

export function writeCompanyMock(state: CompanyMock): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Остаётся копия в памяти.
  }
}

/** Изменить состояние и сохранить; возвращает результат функции. */
export function updateCompanyMock<T>(change: (state: CompanyMock) => T): T {
  const state = readCompanyMock();
  const result = change(state);
  writeCompanyMock(state);
  return result;
}

export function resetCompanyMock(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // нечего сбрасывать
  }
}
