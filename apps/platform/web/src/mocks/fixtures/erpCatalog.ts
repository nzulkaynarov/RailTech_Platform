import type {
  Brigade,
  CatalogOffer,
  ExchangeRateRow,
  HsCode,
  Manufacturer,
  TechDoc,
  TechDocKind,
} from "../../shared/api/generated/model";

/**
 * Вымышленные данные «Расчёт · Номенклатура и поставщики» и «Техдокументация» для MSW (D2-3, BFF 0.25.0): позиции с
 * предложениями поставщиков, бригады, справочники и файлы-образцы (сгенерированные заглушки без чертежей). Состояние живёт
 * в памяти страницы: изменения видны следующему запросу; `resetErpCatalog()` возвращает исходное (тесты).
 */

/** «Сегодня» мока: сроки цен считаются от него, а не от часов, чтобы снимки и e2e не плыли. */
export const MOCK_TODAY = "2026-10-28";
const EXPIRING_DAYS = 14;

export interface MockOffer {
  id: string;
  itemId: string;
  supplierId: string;
  supplier_sku: string;
  amount: string;
  currency: string;
  quota_qty: number;
  min_order_qty: number;
  in_stock_lead_days: number;
  order_lead_days: number;
  stock_status: string | null;
  valid_from: string | null;
  valid_until: string | null;
  is_active: boolean;
}

export interface MockItem {
  id: string;
  sku: string;
  name: string;
  kind: "stock" | "on_order" | "service_fixed" | "service_milestones" | "service_time";
  unitId: string | null;
  vat_rate: string | null;
  categoryId: string | null;
  status: "DRAFT" | "PUBLISHED";
  description: string;
  gost_drawing: string;
  hs_code: string;
  brand: string | null;
}

export interface MockSupplier {
  id: string;
  name: string;
  tin: string;
  country: string;
  contact_person: string;
  phone: string;
  email: string;
  website: string;
  legal_address: string;
}

export interface MockBrigade extends Omit<Brigade, "rate" | "rate_visible"> {
  rate: { amount: string; currency: string; unit: "day" | "hour" } | null;
}

export interface MockDoc {
  doc: Omit<TechDoc, "deal"> & { dealId: string | null };
  bytes: Uint8Array;
}

export interface MockDeal {
  id: number;
  title: string;
  company: string;
  stage_code: string;
  created_at: string;
}

export const UNITS = [
  { id: "1", code: "pcs", name: "шт" },
  { id: "2", code: "m", name: "м" },
  { id: "3", code: "set", name: "компл." },
  { id: "4", code: "md", name: "чел.-день" },
  { id: "5", code: "svc", name: "услуга" },
];
export const CURRENCIES = [
  { code: "UZS", symbol: "сум" },
  { code: "USD", symbol: "$" },
  { code: "EUR", symbol: "€" },
];
export const COUNTRIES = [
  { id: "1", name: "Узбекистан" },
  { id: "2", name: "Россия" },
  { id: "3", name: "Германия" },
];
export const DEALS: MockDeal[] = [
  {
    id: 905,
    title: "Монтаж стрелочных переводов",
    company: "АО «Пример-Рельс»",
    stage_code: "CALCULATING",
    created_at: "2026-10-05T09:00:00Z",
  },
  {
    id: 904,
    title: "Поставка рельсов Р65",
    company: "ООО «Демо-Путь»",
    stage_code: "CONTRACT_SIGNED",
    created_at: "2026-10-01T09:00:00Z",
  },
];

/** Номер для показа: `ЗВ-2026-905` (заявка) или `ПР-…` (проект, договор подписан) — как считает BFF до ERP-09. */
export function dealNumber(deal: MockDeal): string {
  const prefix = deal.stage_code === "CONTRACT_SIGNED" ? "ПР" : "ЗВ";
  return `${prefix}-${deal.created_at.slice(0, 4)}-${String(deal.id).padStart(3, "0")}`;
}

/** Сохранённый «образец» файла: корректный PDF с латинским текстом-заглушкой (без чертежей и реальных документов). */
export function makePdf(title: string, lines: readonly string[]): Uint8Array {
  const text = [title, ...lines];
  const stream = [
    "0.2 0.2 0.2 RG 1 w 60 740 475 -2 re S",
    ...text.map(
      (line, index) =>
        `BT /F1 ${String(index === 0 ? 18 : 12)} Tf 60 ${String(760 - index * 22)} Td (${line.replace(/[()\\]/g, "")}) Tj ET`,
    ),
    "60 400 200 150 re S 60 400 m 260 550 l S 60 550 m 260 400 l S",
  ].join("\n");
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${String(stream.length)} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let out = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((body, index) => {
    offsets.push(out.length);
    out += `${String(index + 1)} 0 obj\n${body}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${String(objects.length + 1)}\n0000000000 65535 f \n`;
  for (const offset of offsets) out += `${String(offset).padStart(10, "0")} 00000 n \n`;
  out += `trailer\n<< /Size ${String(objects.length + 1)} /Root 1 0 R >>\nstartxref\n${String(xref)}\n%%EOF\n`;
  return new TextEncoder().encode(out);
}

function offer(
  id: number,
  itemId: string,
  supplierId: string,
  amount: string,
  currency: string,
  extra: Partial<MockOffer> = {},
): MockOffer {
  return {
    id: String(id),
    itemId,
    supplierId,
    supplier_sku: `П-${String(id).padStart(3, "0")}`,
    amount,
    currency,
    quota_qty: 0,
    min_order_qty: 1,
    in_stock_lead_days: 0,
    order_lead_days: 14,
    stock_status: null,
    valid_from: null,
    valid_until: "2027-03-31",
    is_active: true,
    ...extra,
  };
}

function seedItems(): MockItem[] {
  const base = {
    status: "PUBLISHED" as const,
    description: "",
    gost_drawing: "",
    hs_code: "",
    brand: null,
  };
  return [
    {
      ...base,
      id: "1",
      sku: "RT-0001",
      name: "Кабель силовой ВВГнг 3×2,5",
      kind: "stock",
      unitId: "2",
      vat_rate: null,
      categoryId: "5",
      description: "Кабель медный с ПВХ-изоляцией, негорючий",
      gost_drawing: "ГОСТ 31996",
      hs_code: "8544",
      brand: "Электрокабель-Тест",
    },
    {
      ...base,
      id: "2",
      sku: "RT-0002",
      name: "Реле защиты РЗ-1",
      kind: "on_order",
      unitId: "1",
      vat_rate: "12.00",
      categoryId: "5",
      hs_code: "8536",
    },
    {
      ...base,
      id: "3",
      sku: "RT-0003",
      name: "Рельс Р65, 25 м",
      kind: "stock",
      unitId: "1",
      vat_rate: null,
      categoryId: "1",
      gost_drawing: "ГОСТ Р 51685",
      hs_code: "7302",
      brand: "Рельс-Сталь",
    },
    {
      ...base,
      id: "4",
      sku: "RT-0004",
      name: "Монтаж стрелочного перевода",
      kind: "service_fixed",
      unitId: "5",
      vat_rate: "12.00",
      categoryId: "1",
    },
    {
      ...base,
      id: "5",
      sku: "RT-0005",
      name: "Пусконаладочные работы",
      kind: "service_time",
      unitId: "4",
      vat_rate: "0.00",
      categoryId: null,
      status: "DRAFT",
    },
  ];
}

function seedOffers(): MockOffer[] {
  return [
    offer(1, "1", "1", "12.50", "USD", {
      quota_qty: 500,
      min_order_qty: 10,
      in_stock_lead_days: 2,
      stock_status: "IN_STOCK",
      valid_until: "2026-12-31",
    }),
    offer(2, "1", "2", "13.10", "USD", {
      quota_qty: 120,
      in_stock_lead_days: 5,
      valid_until: "2026-11-05",
    }),
    offer(3, "2", "1", "310.00", "USD", { order_lead_days: 21, valid_until: "2026-11-12" }),
    offer(4, "3", "2", "1850000.00", "UZS", {
      quota_qty: 40,
      min_order_qty: 4,
      in_stock_lead_days: 7,
      stock_status: "IN_STOCK",
      valid_until: "2027-01-31",
    }),
    offer(5, "3", "3", "1790000.00", "UZS", {
      quota_qty: 0,
      order_lead_days: 30,
      valid_until: "2026-10-20",
    }),
  ];
}

function seedSuppliers(): MockSupplier[] {
  return [
    {
      id: "1",
      name: "ООО «Поставщик Север»",
      tin: "300000777",
      country: "Узбекистан",
      contact_person: "Отдел продаж",
      phone: "+998 00 000 00 01",
      email: "sales@sever.example",
      website: "https://sever.example",
      legal_address: "г. Демоград, ул. Вымышленная, 10",
    },
    {
      id: "2",
      name: "АО «Южный Металл»",
      tin: "300000888",
      country: "Россия",
      contact_person: "Менеджер по ЖД-материалам",
      phone: "+7 000 000-00-02",
      email: "rail@yug.example",
      website: "",
      legal_address: "г. Примерск, пр. Образцовый, 5",
    },
    {
      id: "3",
      name: "ИП «Восточный склад»",
      tin: "300000999",
      country: "Узбекистан",
      contact_person: "",
      phone: "",
      email: "",
      website: "",
      legal_address: "",
    },
  ];
}

function seedBrigades(): MockBrigade[] {
  return [
    {
      id: "1",
      name: "Бригада монтажа №1",
      kind: "brigade",
      specialization: "Монтаж путевого оборудования",
      headcount: 4,
      rate: { amount: "900000.00", currency: "UZS", unit: "day" },
      note: "",
      is_active: true,
    },
    {
      id: "2",
      name: "Группа ПНР",
      kind: "brigade",
      specialization: "Пусконаладка устройств СЦБ",
      headcount: 3,
      rate: { amount: "1200000.00", currency: "UZS", unit: "day" },
      note: "Выезд по области",
      is_active: true,
    },
    {
      id: "3",
      name: "Сергей Образцов (электромонтаж)",
      kind: "person",
      specialization: "Электромонтаж, подрядчик",
      headcount: 1,
      rate: { amount: "150000.00", currency: "UZS", unit: "hour" },
      note: "",
      is_active: true,
    },
  ];
}

function seedHs(): HsCode[] {
  const row = (
    id: number,
    code: string,
    name: string,
    unit: string,
    extra: Partial<HsCode> = {},
  ): HsCode => ({
    id: String(id),
    code,
    name,
    unit_name: unit,
    extra_unit_name: "",
    level: code.length as HsCode["level"],
    valid_from: null,
    valid_until: null,
    is_active: true,
    source: "справочник",
    ...extra,
  });
  return [
    row(1, "73", "Изделия из чёрных металлов", "кг"),
    row(2, "7302", "Материалы для рельсовых путей из чёрных металлов", "кг"),
    row(3, "8536", "Аппаратура для коммутации электрических цепей", "кг", {
      extra_unit_name: "шт",
    }),
    row(4, "8544", "Провода и кабели изолированные", "кг", { extra_unit_name: "м" }),
    row(5, "854449", "Провода на напряжение до 80 В", "кг", {
      valid_until: "2026-06-30",
      is_active: false,
    }),
  ];
}

function seedManufacturers(): Manufacturer[] {
  return [
    {
      id: "1",
      name: "Электрокабель-Тест",
      country_id: "1",
      country_name: "Узбекистан",
      website: "",
      is_active: true,
    },
    {
      id: "2",
      name: "Рельс-Сталь",
      country_id: "2",
      country_name: "Россия",
      website: "https://rail-steel.example",
      is_active: true,
    },
    {
      id: "3",
      name: "Brand Test GmbH",
      country_id: "3",
      country_name: "Германия",
      website: "",
      is_active: false,
    },
  ];
}

function seedRates(): ExchangeRateRow[] {
  return [
    { id: "1", currency: "USD", rate_to_uzs: "12650.5", rate_date: "2026-10-28", source: "CBU" },
    { id: "2", currency: "EUR", rate_to_uzs: "13840.2", rate_date: "2026-10-28", source: "CBU" },
    { id: "3", currency: "USD", rate_to_uzs: "12640", rate_date: "2026-10-27", source: "MANUAL" },
    { id: "4", currency: "RUB", rate_to_uzs: "135.8", rate_date: "2026-10-28", source: "CBU" },
  ];
}

function seedDocs(items: readonly MockItem[]): MockDoc[] {
  const make = (
    id: number,
    kind: TechDocKind,
    title: string,
    name: string,
    productId: string | null,
    dealId: string | null,
    by: string,
    at: string,
  ): MockDoc => {
    const bytes = makePdf(`SAMPLE ${kind.toUpperCase()} (placeholder)`, [
      "Generated sample file. No real drawings or documents.",
      title.replace(/[^\x20-\x7e]/g, "?"),
    ]);
    return {
      bytes,
      doc: {
        id: String(id),
        kind,
        title,
        original_name: name,
        content_type: "application/pdf",
        size_bytes: bytes.length,
        previewable: true,
        product: productId ? refOf(items, productId) : null,
        dealId,
        uploaded_by: by,
        created_at: at,
      },
    };
  };
  return [
    make(
      1,
      "tz",
      "ТЗ на стрелочные переводы",
      "tz-strelki.pdf",
      null,
      "905",
      "Гл. инженер",
      "2026-10-26T09:10:00Z",
    ),
    make(
      2,
      "drawing",
      "Чертёж рельса Р65",
      "drawing-r65.pdf",
      "3",
      "904",
      "Гл. инженер",
      "2026-10-25T14:00:00Z",
    ),
    make(
      3,
      "certificate",
      "Сертификат соответствия на кабель",
      "cert-vvg.pdf",
      "1",
      null,
      "Снабженец",
      "2026-10-24T11:30:00Z",
    ),
    make(
      4,
      "pnr",
      "Регламент ПНР устройств СЦБ",
      "pnr-sctb.pdf",
      "5",
      null,
      "Гл. инженер",
      "2026-10-22T08:00:00Z",
    ),
  ];
}

// --- состояние -------------------------------------------------------------------------------

interface State {
  items: MockItem[];
  offers: MockOffer[];
  suppliers: MockSupplier[];
  brigades: MockBrigade[];
  hs: HsCode[];
  manufacturers: Manufacturer[];
  rates: ExchangeRateRow[];
  docs: MockDoc[];
  next: number;
}

function seed(): State {
  const items = seedItems();
  return {
    items,
    offers: seedOffers(),
    suppliers: seedSuppliers(),
    brigades: seedBrigades(),
    hs: seedHs(),
    manufacturers: seedManufacturers(),
    rates: seedRates(),
    docs: seedDocs(items),
    next: 100,
  };
}

let state: State = seed();

export const readErpCatalog = (): State => state;
export function resetErpCatalog(): void {
  state = seed();
}
export const nextId = (): string => String(state.next++);

function refOf(
  items: readonly MockItem[],
  itemId: string,
): { id: string; name: string; sku: string } | null {
  const item = items.find((i) => i.id === itemId);
  return item ? { id: item.id, name: item.name, sku: item.sku } : null;
}

export function productRef(itemId: string): { id: string; name: string; sku: string } | null {
  return refOf(state.items, itemId);
}

/** Срок цены на «сегодня» мока: действует, истекает в ближайшие 14 дней, истёк. */
export function validityOf(validUntil: string | null): CatalogOffer["validity"] {
  if (!validUntil) return "ok";
  if (validUntil < MOCK_TODAY) return "expired";
  const limit = new Date(`${MOCK_TODAY}T00:00:00Z`);
  limit.setUTCDate(limit.getUTCDate() + EXPIRING_DAYS);
  return validUntil <= limit.toISOString().slice(0, 10) ? "expiring" : "ok";
}
