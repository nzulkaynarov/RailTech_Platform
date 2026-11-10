import { HttpResponse, http } from "msw";

import type {
  Brigade,
  BrigadeCreate,
  BrigadeUpdate,
  CatalogItem,
  CatalogItemCreate,
  CatalogItemDetail,
  CatalogItemKind,
  CatalogItemUpdate,
  CatalogOffer,
  CatalogPrice,
  CatalogReviewInfo,
  CatalogReturnIssue,
  CategoryProposalIn,
  CategoryRequest,
  HsCode,
  HsCodeCreate,
  HsCodeUpdate,
  Manufacturer,
  ManufacturerCreate,
  ManufacturerUpdate,
  PriceImportApplyIn,
  PriceImportReport,
  SupplierCreate,
  SupplierDetail,
  SupplierOfferCreate,
  SupplierOfferUpdate,
  SupplierRow,
  SupplierUpdate,
  CatalogImage,
  CatalogTechDocRef,
  TechDoc,
  TechDocReview,
  TechDocUpdate,
} from "../shared/api/generated/model";
import {
  COUNTRIES,
  CURRENCIES,
  DEALS,
  DELIVERY_BASES,
  DOC_KINDS,
  MOCK_TODAY,
  type MockBrigade,
  type MockImage,
  type MockItem,
  type MockDoc,
  type MockOffer,
  type MockProposal,
  type MockSupplier,
  UNITS,
  dealNumber,
  kindName,
  nextId,
  productRef,
  readErpCatalog,
  validityOf,
} from "./fixtures/erpCatalog";
import { readCompanyMock, updateCompanyMock } from "./fixtures/company";
import { partnerPriceVisibility } from "./erpSupplierAccess";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки «Расчёт · Номенклатура и партнёры» и «Техдокументация» (D2-3, BFF 0.26.0). Права — как в BFF: раздел `erp.stock`
 * (чтение — `read`, изменения — `full`); цена закупки — поле `supplier_prices`; ставка бригады — `cost_margin` или раздел
 * `erp.calc.services`. Отказы и коды причин — те же, что у настоящего ERP, чтобы экран и e2e видели настоящее поведение.
 * Запросы на категории и курс делят состояние с Admin · Компания (`fixtures/company.ts`).
 */
type Level = "read" | "full";

function failure(
  status: number,
  code: string,
  message: string,
  source: "bff" | "erp" = "bff",
  details?: Record<string, unknown>,
) {
  return HttpResponse.json({ code, message, source, ...(details ? { details } : {}) }, { status });
}

const invalid = (field: string, reason: string) =>
  failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "erp", {
    fields: [field],
    reason,
  });

const notFound = () => failure(404, "NOT_FOUND", "Не найдено");

interface Caller {
  full: boolean;
  prices: boolean;
  rates: boolean;
  email: string;
  name: string;
}

function guard(need: Level): Caller | Response {
  const session = readSession();
  if (!session) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  const me = buildMe({ ...session, activeRole: null });
  const level = me?.resources["erp.stock"];
  if (!me || !level || (need === "full" && level !== "full")) {
    return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
      resource: "erp.stock",
      need,
    });
  }
  const fields = me.restricted_fields ?? [];
  return {
    full: level === "full",
    prices: fields.includes("supplier_prices"),
    rates: fields.includes("cost_margin") || me.resources["erp.calc.services"] !== undefined,
    email: me.email,
    name: me.name,
  };
}

const isResponse = (value: Caller | Response): value is Response => value instanceof Response;

function pageOf<T>(rows: T[], params: URLSearchParams) {
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const size = Math.min(200, Math.max(1, Number(params.get("page_size") ?? 25) || 25));
  return {
    items: rows.slice((page - 1) * size, page * size),
    total: rows.length,
    page,
    page_size: size,
  };
}

const contains = (haystack: string, needle: string | null) =>
  !needle || haystack.toLowerCase().includes(needle.trim().toLowerCase());

// --- сборка ответов ----------------------------------------------------------------------------

function unitOf(id: string | null) {
  const unit = UNITS.find((u) => u.id === id);
  return unit ? { id: unit.id, code: unit.code, name: unit.name } : null;
}

function categoryOf(id: string | null) {
  const found = readCompanyMock().categories.find((c) => c.id === id);
  return found ? { id: found.id, name: found.name } : null;
}

const HOUR_MS = 3_600_000;

/** Что ждёт решения (PART-3): карточка на проверке или предложения партнёра; срок — сутки от отправки (выходные в моке не считаются). */
function reviewOf(item: MockItem): CatalogReviewInfo | null {
  const partnerProposals = item.proposals.filter((p) => p.partner);
  const open = item.status === "REVIEW" ? item.review : null;
  if (!open && partnerProposals.length === 0) return null;
  const submitted = open?.submitted_at ?? partnerProposals[0]?.created_at ?? MOCK_TODAY;
  const supplierId = open ? item.sourceSupplierId : (partnerProposals[0]?.supplierId ?? null);
  return {
    kind: open ? "card" : "changes",
    partner: supplierName(supplierId),
    submitted_at: submitted,
    due_at: new Date(Date.parse(submitted) + 24 * HOUR_MS).toISOString(),
    overdue: open ? open.overdue : submitted.slice(0, 10) < "2026-10-28",
  };
}

const completenessOf = (item: MockItem) => 100 - missingOf(item).length * 25;

function rowOf(item: MockItem): CatalogItem {
  const { offers } = readErpCatalog();
  const own = offers.filter((o) => o.itemId === item.id && o.is_active);
  const live = own.filter((o) => validityOf(o.valid_until) !== "expired");
  const dates = live.map((o) => o.valid_until).filter((d): d is string => d !== null);
  const company = readCompanyMock();
  return {
    id: item.id,
    sku: item.sku,
    name: item.name,
    kind: item.kind,
    unit: unitOf(item.unitId),
    vat_rate: item.vat_rate,
    vat_effective: item.vat_rate ?? company.platform.vat_rate,
    category: categoryOf(item.categoryId),
    status: item.status,
    offers_count: own.length,
    nearest_valid_until: dates.sort()[0] ?? null,
    docs_count: readErpCatalog().docs.filter((d) => d.doc.product?.id === item.id).length,
    proposals_count: item.proposals.length,
    review: reviewOf(item),
    completeness: completenessOf(item),
  };
}

function offerOf(offer: MockOffer, prices: boolean): CatalogOffer {
  const state = readErpCatalog();
  const supplier = state.suppliers.find((s) => s.id === offer.supplierId);
  const product = productRef(offer.itemId);
  if (!supplier || !product) throw new Error(`предложение ${offer.id} без партнёра или позиции`);
  return {
    id: offer.id,
    supplier: { id: supplier.id, name: supplier.name },
    product,
    supplier_sku: offer.supplier_sku,
    price: prices ? { amount: offer.amount, currency: offer.currency } : null,
    quota_qty: offer.quota_qty,
    min_order_qty: offer.min_order_qty,
    in_stock_lead_days: offer.in_stock_lead_days,
    order_lead_days: offer.order_lead_days,
    stock_status: offer.stock_status,
    delivery_basis: offer.delivery_basis,
    lead_time: offer.lead_time,
    source: offer.source,
    updated_at: offer.updated_at,
    valid_from: offer.valid_from,
    valid_until: offer.valid_until,
    is_active: offer.is_active,
    validity: validityOf(offer.valid_until),
  };
}

/** Порог публикации мока: название, категория, единица и код ТН ВЭД (как полнота ERP по умолчанию). */
function missingOf(item: MockItem): string[] {
  return [
    ...(item.categoryId ? [] : ["category"]),
    ...(item.unitId ? [] : ["uom"]),
    ...(item.hs_code ? [] : ["hs_code"]),
  ];
}

function supplierName(id: string | null): { id: string; name: string } | null {
  const supplier = readErpCatalog().suppliers.find((s) => s.id === id);
  return supplier ? { id: supplier.id, name: supplier.name } : null;
}

/** Что покажет каталог клиенту: видимость — карточка → договорённость с партнёром → компания («по запросу»). */
function catalogPriceOf(item: MockItem): CatalogPrice {
  const partner = item.sourceSupplierId ? partnerPriceVisibility(item.sourceSupplierId) : "";
  const visibility = partner === "" ? "on_request" : partner;
  return {
    visibility,
    source: partner === "" ? "company" : "partner",
    price:
      visibility === "cabinet" && item.list_price
        ? { amount: item.list_price, currency: "UZS" }
        : null,
  };
}

function detailOf(item: MockItem, who: Caller): CatalogItemDetail {
  const state = readErpCatalog();
  return {
    ...rowOf(item),
    description: item.description,
    gost_drawing: item.gost_drawing,
    hs_code: item.hs_code,
    manufacturer_part_number: item.mpn,
    brand: item.brand,
    brand_id: item.brandId,
    source_supplier: supplierName(item.sourceSupplierId),
    offers: state.offers.filter((o) => o.itemId === item.id).map((o) => offerOf(o, who.prices)),
    prices_visible: who.prices,
    tech_docs: state.docs.filter((d) => d.doc.product?.id === item.id).map((d) => docRefOf(d.doc)),
    images: item.images.map((image, index) => imageOf(image, index)),
    origin: originOf(item),
    warranty: warrantyOf(item),
    proposals: item.proposals.map((p) => ({
      id: p.id,
      field: p.field,
      current: p.current,
      proposed: p.proposed,
      supplier: supplierName(p.supplierId),
      created_at: p.created_at,
    })),
    publish: { publishable: missingOf(item).length === 0, missing: missingOf(item) },
    catalog_price: catalogPriceOf(item),
  };
}

function docRefOf(doc: MockDoc["doc"]): CatalogTechDocRef {
  return {
    id: doc.id,
    title: doc.title,
    kind: doc.kind,
    kind_name: doc.kind_name,
    number: doc.number,
    issued_by: doc.issued_by,
    issued_at: doc.issued_at,
    valid_until: doc.valid_until,
    is_expired: doc.is_expired,
    client_visible: doc.client_visible,
    review_state: doc.review_state,
    partner: doc.partner,
    original_name: doc.original_name,
    size_bytes: doc.size_bytes,
    previewable: doc.previewable,
  };
}

function imageOf(image: MockImage, index: number): CatalogImage {
  return { id: image.id, is_main: image.is_main, sort_order: index, alt: image.alt };
}

const countryRef = (id: string | null) => {
  const found = COUNTRIES.find((c) => c.id === id);
  return found ? { id: found.id, name: found.name } : null;
};

function originOf(item: MockItem): CatalogItemDetail["origin"] {
  const brand = readErpCatalog().manufacturers.find((m) => m.id === item.brandId);
  const own = countryRef(item.countryId);
  const fromBrand = countryRef(brand?.country_id ?? null);
  return {
    own,
    effective: own ?? fromBrand,
    brand: fromBrand,
    source: own ? "item" : fromBrand ? "brand" : "none",
  };
}

function warrantyOf(item: MockItem): CatalogItemDetail["warranty"] {
  const company = readCompanyMock().quote.default_warranty_months ?? null;
  const months = item.warranty_months;
  return {
    months,
    terms: item.warranty_terms,
    effective_months: months ?? company,
    company_months: company,
    source: months !== null ? "item" : company !== null ? "company" : "none",
  };
}

function supplierRowOf(supplier: MockSupplier): SupplierRow {
  const own = readErpCatalog().offers.filter((o) => o.supplierId === supplier.id && o.is_active);
  const states = own.map((o) => validityOf(o.valid_until));
  const live = own
    .flatMap((o) =>
      validityOf(o.valid_until) !== "expired" && o.valid_until ? [o.valid_until] : [],
    )
    .sort();
  return {
    id: supplier.id,
    name: supplier.name,
    tin: supplier.tin,
    registration_number: supplier.registration_number,
    country: supplier.country,
    country_id: supplier.country_id,
    currency: supplier.currency,
    is_manufacturer: supplier.is_manufacturer,
    offers_count: own.length,
    expired_count: states.filter((s) => s === "expired").length,
    expiring_count: states.filter((s) => s === "expiring").length,
    nearest_valid_until: live[0] ?? null,
  };
}

function brigadeOf(brigade: MockBrigade, who: Caller): Brigade {
  return {
    ...brigade,
    rate: who.rates ? brigade.rate : null,
    rate_visible: who.rates,
  };
}

const KINDS: CatalogItemKind[] = [
  "stock",
  "on_order",
  "service_fixed",
  "service_milestones",
  "service_time",
];

const erpForbidden = (code: string) =>
  failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "erp", {
    backend_status: 403,
    backend_code: code,
  });

const conflict = (reason: string, message: string) =>
  failure(409, "CONFLICT", message, "erp", { reason, backend_status: 409 });

async function body<B>(request: Request): Promise<B> {
  return (await request.json().catch(() => ({}))) as B;
}

const DECIMAL = /^\d{1,12}(\.\d{1,2})?$/;

interface Upload {
  fields: Record<string, string>;
  file: { name: string; type: string; bytes: Uint8Array } | null;
}

/**
 * Разбор multipart по байтам, без `request.formData()`: в jsdom (vitest) разбор форм в Node не знает чужой `File`, а мок
 * работает и там, и в браузере. Содержимое файла сохраняется как есть (PDF не портится перекодировкой).
 */
async function parseUpload(request: Request): Promise<Upload | null> {
  const boundary = /boundary=([^;]+)/.exec(request.headers.get("content-type") ?? "")?.[1];
  if (!boundary) return null;
  const bytes = new Uint8Array(await request.arrayBuffer());
  let raw = "";
  for (let at = 0; at < bytes.length; at += 8192) {
    raw += String.fromCharCode(...bytes.subarray(at, at + 8192));
  }
  const upload: Upload = { fields: {}, file: null };
  for (const part of raw.split(`--${boundary}`)) {
    const split = part.indexOf("\r\n\r\n");
    if (split < 0) continue;
    const head = part.slice(0, split);
    const field = /name="([^"]*)"/.exec(head)?.[1];
    if (!field) continue;
    const body = part.slice(split + 4).replace(/\r\n$/, "");
    const content = Uint8Array.from(body, (c) => c.charCodeAt(0));
    const filename = /filename="([^"]*)"/.exec(head)?.[1];
    if (filename !== undefined && (field === "file" || field === "image")) {
      upload.file = {
        name: new TextDecoder().decode(Uint8Array.from(filename, (c) => c.charCodeAt(0))),
        type: /Content-Type:\s*([^\r\n]+)/i.exec(head)?.[1] ?? "",
        bytes: content,
      };
    } else {
      upload.fields[field] = new TextDecoder().decode(content);
    }
  }
  return upload;
}

function supplierDetailOf(supplier: MockSupplier, who: Caller): SupplierDetail {
  const state = readErpCatalog();
  const offers = state.offers.filter((o) => o.supplierId === supplier.id);
  const brands = new Map<string, string>();
  for (const offer of offers) {
    const item = state.items.find((i) => i.id === offer.itemId);
    if (item?.brandId && item.brand && offer.is_active) brands.set(item.brandId, item.brand);
  }
  return {
    ...supplierRowOf(supplier),
    contact_person: supplier.contact_person,
    phone: supplier.phone,
    email: supplier.email,
    website: supplier.website,
    legal_address: supplier.legal_address,
    offers: offers.map((o) => offerOf(o, who.prices)),
    prices_visible: who.prices,
    brands: [...brands].map(([id, name]) => ({ id, name })),
    manufactured_brands: state.manufacturers
      .filter((m) => m.company_id === supplier.id)
      .map((m) => ({ id: m.id, name: m.name })),
  };
}

/** Снимок цены в историю (CAT-1): как pghistory в ERP — при создании и каждой правке. */
function snapshot(offer: MockOffer, by: string | null): void {
  offer.updated_at = `${MOCK_TODAY}T${String(9 + offer.history.length).padStart(2, "0")}:00:00Z`;
  offer.history.unshift({
    at: offer.updated_at,
    amount: offer.amount,
    currency: offer.currency,
    valid_from: offer.valid_from,
    valid_until: offer.valid_until,
    delivery_basis: offer.delivery_basis,
    source: offer.source,
    by,
  });
}

function applyProposal(item: MockItem, proposal: MockProposal): void {
  if (proposal.field === "name") item.name = proposal.proposed;
  if (proposal.field === "description") item.description = proposal.proposed;
  if (proposal.field === "hs_code") item.hs_code = proposal.proposed;
  if (proposal.field === "gost_drawing") item.gost_drawing = proposal.proposed;
}

// --- загрузка прайса (CAT-1): детерминированный сценарий вымышленного прайса -----------------------

interface ImportJob {
  report: PriceImportReport;
}

const jobs = new Map<string, ImportJob>();

/** Строки «файла» мока: новая позиция, цена на опубликованную карточку с другим наименованием, строка с ошибкой. */
const IMPORT_ROWS = [
  {
    row: 2,
    name: "Клапан запорный КЗ-50",
    mpn: "KZ-50",
    amount: "84.00",
    currency: "EUR",
    lead: "30 дн.",
  },
  {
    row: 3,
    name: "Кабель силовой ВВГнг-LS 3×2,5",
    mpn: "ВВГ-3-2.5",
    amount: "11.90",
    currency: "EUR",
    lead: "21 дн.",
  },
] as const;

function runImport(
  supplier: MockSupplier,
  write: boolean,
  validFrom: string | null,
  validUntil: string | null,
  ai: boolean,
): PriceImportReport {
  const state = readErpCatalog();
  const report: PriceImportReport = {
    checked: !write,
    items_created: 0,
    items_matched: 0,
    offers_created: 0,
    offers_updated: 0,
    proposal_count: 0,
    proposals: [],
    error_count: 1,
    errors: [{ row: 4, code: "UNKNOWN_CURRENCY", value: "XYZ" }],
    warning_count: 0,
    warnings: [],
    rows_truncated: 0,
    unpublishable: 0,
    rows_token: ai && !write ? "f".repeat(32) : null,
    ai_used: ai ? true : null,
  };
  for (const line of IMPORT_ROWS) {
    let item = state.items.find((i) => i.mpn === line.mpn);
    if (item) report.items_matched += 1;
    else {
      report.items_created += 1;
      report.unpublishable += 1;
      if (write) {
        const id = nextId();
        item = {
          id,
          sku: `RT-${id.padStart(4, "0")}`,
          name: line.name,
          kind: "on_order",
          unitId: "1",
          vat_rate: null,
          categoryId: null,
          status: "DRAFT",
          review: null,
          list_price: null,
          description: "",
          gost_drawing: "",
          hs_code: "",
          brand: null,
          brandId: null,
          mpn: line.mpn,
          sourceSupplierId: supplier.id,
          proposals: [],
          countryId: null,
          warranty_months: null,
          warranty_terms: "",
          images: [],
        };
        state.items.push(item);
      }
    }
    const foreign = item && (item.status === "PUBLISHED" || item.sourceSupplierId !== supplier.id);
    if (item && foreign && item.name !== line.name) {
      report.proposal_count += 1;
      report.proposals.push({
        row: line.row,
        product_id: item.id,
        product_name: item.name,
        field: "name",
        current: item.name,
        proposed: line.name,
      });
      const open = item.proposals.find((p) => p.field === "name" && p.supplierId === supplier.id);
      if (write && !open)
        item.proposals.push({
          id: nextId(),
          field: "name",
          current: item.name,
          proposed: line.name,
          supplierId: supplier.id,
          created_at: `${MOCK_TODAY}T10:00:00Z`,
        });
    }
    const existing = item
      ? state.offers.find((o) => o.itemId === item.id && o.supplierId === supplier.id)
      : undefined;
    if (existing) report.offers_updated += 1;
    else report.offers_created += 1;
    if (!write || !item) continue;
    const offer: MockOffer = existing ?? {
      id: nextId(),
      itemId: item.id,
      supplierId: supplier.id,
      supplier_sku: "",
      amount: line.amount,
      currency: line.currency,
      quota_qty: 0,
      min_order_qty: 1,
      in_stock_lead_days: 0,
      order_lead_days: 30,
      stock_status: null,
      valid_from: null,
      valid_until: null,
      is_active: true,
      delivery_basis: null,
      lead_time: "",
      source: "price_list",
      updated_at: "",
      history: [],
    };
    offer.amount = line.amount;
    offer.currency = line.currency;
    offer.lead_time = line.lead;
    offer.source = "price_list";
    if (validFrom) offer.valid_from = validFrom;
    if (validUntil) offer.valid_until = validUntil;
    snapshot(offer, null);
    if (!existing) state.offers.push(offer);
  }
  return report;
}

export const erpCatalogHandlers = [
  http.get("*/erp/catalog/price-import/template", () => {
    const who = guard("read");
    if (isResponse(who)) return who;
    return new HttpResponse(new Uint8Array([0x50, 0x4b, 0x03, 0x04]), {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": 'attachment; filename="price-template.xlsx"',
      },
    });
  }),
  http.post("*/erp/catalog/price-import/apply-checked", async ({ request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    if (!who.prices) return erpForbidden("SUPPLIER_PRICES_REQUIRED");
    const data = await body<Partial<PriceImportApplyIn>>(request);
    const supplier = readErpCatalog().suppliers.find((s) => s.id === data.supplier_id);
    if (!supplier || !data.rows_token) return invalid("rows_token", "rows_token_invalid");
    const id = `job-${nextId()}`;
    jobs.set(id, {
      report: runImport(supplier, true, data.valid_from ?? null, data.valid_until ?? null, true),
    });
    return HttpResponse.json({ job_id: id, mode: "ai" }, { status: 202 });
  }),
  http.post("*/erp/catalog/price-import", async ({ request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    if (!who.prices)
      return failure(403, "FORBIDDEN", "Прайс загружает тот, кому открыты цены партнёров.", "bff", {
        restricted: "supplier_prices",
      });
    const params = new URL(request.url).searchParams;
    const supplier = readErpCatalog().suppliers.find((s) => s.id === params.get("supplier_id"));
    if (!supplier) return invalid("supplier_id", "supplier_not_found");
    const upload = await parseUpload(request);
    if (!upload?.file) return invalid("file", "no_file_provided");
    const from = params.get("valid_from");
    const until = params.get("valid_until");
    if (from && until && until < from)
      return invalid("valid_until", "offer_validity_range_invalid");
    const mode = params.get("mode") === "ai" ? "ai" : "xlsx";
    const write = params.get("check") === "false";
    const id = `job-${nextId()}`;
    jobs.set(id, { report: runImport(supplier, write, from, until, mode === "ai") });
    return HttpResponse.json({ job_id: id, mode }, { status: 202 });
  }),
  http.get("*/erp/catalog/price-import/:job", ({ params }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const job = jobs.get(String(params["job"]));
    if (!job) return notFound();
    return HttpResponse.json({ state: "done", report: job.report, error: null });
  }),

  http.get("*/erp/catalog/lookups", () => {
    const who = guard("read");
    if (isResponse(who)) return who;
    return HttpResponse.json({
      units: UNITS,
      categories: readCompanyMock().categories.map((c) => ({
        id: c.id,
        name: c.name,
        parent_id: c.parent_id ?? null,
      })),
      currencies: CURRENCIES,
      countries: COUNTRIES,
      delivery_bases: DELIVERY_BASES,
      document_kinds: DOC_KINDS,
    });
  }),

  // --- позиции
  http.get("*/erp/catalog/items", ({ request }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const params = new URL(request.url).searchParams;
    const q = params.get("q");
    const kind = params.get("kind");
    const category = params.get("category_id");
    const pending = params.get("proposals") === "pending";
    const waiting = params.get("review") === "waiting";
    if (params.get("review") !== null && !waiting) return invalid("review", "review_invalid");
    const found = readErpCatalog().items.filter(
      (i) =>
        (contains(i.name, q) || contains(i.sku, q) || contains(i.gost_drawing, q)) &&
        (!kind || i.kind === kind) &&
        (!category || i.categoryId === category) &&
        (!pending || i.proposals.length > 0) &&
        (!waiting || reviewOf(i) !== null),
    );
    // Очередь проверки: старые отправки сверху
    if (waiting)
      found.sort((a, b) =>
        (reviewOf(a)?.submitted_at ?? "").localeCompare(reviewOf(b)?.submitted_at ?? ""),
      );
    const rows = found.map(rowOf);
    return HttpResponse.json(pageOf(rows, params));
  }),
  http.get("*/erp/catalog/items/:id", ({ params }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const item = readErpCatalog().items.find((i) => i.id === params["id"]);
    return item ? HttpResponse.json(detailOf(item, who)) : notFound();
  }),
  http.post("*/erp/catalog/items", async ({ request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const data = await body<Partial<CatalogItemCreate>>(request);
    if (!data.name?.trim()) return invalid("name", "item_name_required");
    if (!data.kind || !KINDS.includes(data.kind)) return invalid("kind", "item_kind_invalid");
    if (data.vat_rate && Number(data.vat_rate) > 100)
      return invalid("vat_rate", "vat_rate_invalid");
    const state = readErpCatalog();
    const id = nextId();
    const item: MockItem = {
      id,
      sku: `RT-${id.padStart(4, "0")}`,
      name: data.name.trim(),
      kind: data.kind,
      unitId: data.unit_id ?? null,
      vat_rate: data.vat_rate ?? null,
      categoryId: data.category_id ?? null,
      status: "DRAFT",
      review: null,
      list_price: null,
      description: data.description ?? "",
      gost_drawing: "",
      hs_code: "",
      brand: null,
      brandId: null,
      mpn: "",
      sourceSupplierId: null,
      proposals: [],
      countryId: data.country_of_origin_id ?? null,
      warranty_months: data.warranty_months ?? null,
      warranty_terms: data.warranty_terms ?? "",
      images: [],
    };
    state.items.push(item);
    return HttpResponse.json(detailOf(item, who), { status: 201 });
  }),
  http.patch("*/erp/catalog/items/:id", async ({ request, params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const item = readErpCatalog().items.find((i) => i.id === params["id"]);
    if (!item) return notFound();
    const data = await body<CatalogItemUpdate>(request);
    if (data.name !== undefined) {
      if (!data.name.trim()) return invalid("name", "item_name_required");
      item.name = data.name.trim();
    }
    if (data.vat_rate !== undefined) {
      if (data.vat_rate !== null && !(Number(data.vat_rate) >= 0 && Number(data.vat_rate) <= 100))
        return invalid("vat_rate", "vat_rate_invalid");
      item.vat_rate = data.vat_rate === null ? null : Number(data.vat_rate).toFixed(2);
    }
    if (data.unit_id !== undefined) item.unitId = data.unit_id;
    if (data.category_id !== undefined) item.categoryId = data.category_id;
    if (data.kind !== undefined) item.kind = data.kind;
    if (data.description !== undefined) item.description = data.description;
    if (data.brand_id !== undefined) {
      const brand = readErpCatalog().manufacturers.find((m) => m.id === data.brand_id);
      if (data.brand_id !== null && !brand) return invalid("brand_id", "brand_not_found");
      item.brandId = brand?.id ?? null;
      item.brand = brand?.name ?? null;
    }
    if (data.manufacturer_part_number !== undefined) item.mpn = data.manufacturer_part_number;
    if (data.hs_code !== undefined) item.hs_code = data.hs_code;
    if (data.country_of_origin_id !== undefined) {
      if (data.country_of_origin_id !== null && !countryRef(data.country_of_origin_id))
        return invalid("country_of_origin_id", "country_not_found");
      item.countryId = data.country_of_origin_id;
    }
    if (data.warranty_months !== undefined) item.warranty_months = data.warranty_months;
    if (data.warranty_terms !== undefined) item.warranty_terms = data.warranty_terms;
    return HttpResponse.json(detailOf(item, who));
  }),

  // --- фото позиции (CAT-CARD-1): до 10, одно главное, порядок задаёт сотрудник
  http.post("*/erp/catalog/items/:id/images", async ({ request, params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const item = readErpCatalog().items.find((i) => i.id === params["id"]);
    if (!item) return notFound();
    const form = await parseUpload(request);
    const file = form?.file;
    if (!form || !file) return invalid("image", "no_file_provided");
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    const types: Record<string, string> = {
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".png": "image/png",
      ".webp": "image/webp",
    };
    if (!types[ext]) return invalid("image", "file_type_not_allowed");
    if (file.bytes.length > 5 * 1024 * 1024)
      return failure(413, "PAYLOAD_TOO_LARGE", "Фото больше 5 МБ.", "bff", {
        max_bytes: 5 * 1024 * 1024,
      });
    if (item.images.length >= 10) return invalid("image", "image_limit_reached");
    const makeMain = form.fields["is_main"] === "true";
    if (makeMain) for (const other of item.images) other.is_main = false;
    const created: MockImage = {
      id: nextId(),
      alt: (form.fields["alt_text"] ?? "").trim(),
      is_main: makeMain || item.images.length === 0,
      type: types[ext],
      bytes: file.bytes,
    };
    item.images.push(created);
    return HttpResponse.json(imageOf(created, item.images.length - 1), { status: 201 });
  }),
  http.patch("*/erp/catalog/items/:id/images/:image", async ({ request, params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const item = readErpCatalog().items.find((i) => i.id === params["id"]);
    const image = item?.images.find((i) => i.id === params["image"]);
    if (!item || !image) return notFound();
    const data = await body<{ is_main?: boolean; sort_order?: number; alt_text?: string }>(request);
    if (data.alt_text !== undefined) image.alt = data.alt_text.trim();
    if (data.is_main === true) for (const other of item.images) other.is_main = other === image;
    if (data.sort_order !== undefined) {
      item.images.splice(item.images.indexOf(image), 1);
      item.images.splice(Math.min(data.sort_order, item.images.length), 0, image);
    }
    return HttpResponse.json(imageOf(image, item.images.indexOf(image)));
  }),
  http.delete("*/erp/catalog/items/:id/images/:image", ({ params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const item = readErpCatalog().items.find((i) => i.id === params["id"]);
    const index = item?.images.findIndex((i) => i.id === params["image"]) ?? -1;
    if (!item || index < 0) return notFound();
    item.images.splice(index, 1);
    if (item.images.length > 0 && !item.images.some((i) => i.is_main)) {
      const first = item.images[0];
      if (first) first.is_main = true;
    }
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("*/erp/catalog/items/:id/images/:image/content", ({ params }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const item = readErpCatalog().items.find((i) => i.id === params["id"]);
    const image = item?.images.find((i) => i.id === params["image"]);
    if (!image) return notFound();
    return new HttpResponse(image.bytes, {
      headers: { "Content-Type": image.type, "X-Content-Type-Options": "nosniff" },
    });
  }),
  http.post("*/erp/catalog/items/:id/return", async ({ params, request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const item = readErpCatalog().items.find((i) => i.id === params["id"]);
    if (!item) return notFound();
    const data = await body<{ reason?: string | null; issues?: CatalogReturnIssue[] | null }>(
      request,
    );
    if (!(data.reason ?? "").trim() && !(data.issues ?? []).length)
      return invalid("reason", "review_reason_required");
    if (item.status !== "REVIEW")
      return conflict("product_not_on_review", "Карточка уже не на проверке. Обновите страницу.");
    item.status = "RETURNED";
    item.review = null;
    return HttpResponse.json(detailOf(item, who));
  }),
  http.post("*/erp/catalog/items/:id/:action", ({ params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const item = readErpCatalog().items.find((i) => i.id === params["id"]);
    if (!item) return notFound();
    if (params["action"] === "publish") {
      if (missingOf(item).length > 0)
        return conflict("product_incomplete", "Заполните недостающие поля, затем опубликуйте.");
      item.status = "PUBLISHED";
      item.review = null;
    } else if (params["action"] === "unpublish") {
      item.status = "DRAFT";
    } else return notFound();
    return HttpResponse.json(detailOf(item, who));
  }),
  http.post("*/erp/catalog/proposals/:id/:decision", ({ params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const item = readErpCatalog().items.find((i) => i.proposals.some((p) => p.id === params["id"]));
    const proposal = item?.proposals.find((p) => p.id === params["id"]);
    if (!item || !proposal) return conflict("proposal_decided", "Изменение уже решено.");
    if (params["decision"] === "accept") applyProposal(item, proposal);
    item.proposals = item.proposals.filter((p) => p.id !== proposal.id);
    return HttpResponse.json(detailOf(item, who));
  }),

  // --- партнёры
  http.get("*/erp/catalog/suppliers", ({ request }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const params = new URL(request.url).searchParams;
    const q = params.get("q");
    const rows = readErpCatalog()
      .suppliers.filter(
        (s) => contains(s.name, q) || contains(s.tin, q) || contains(s.registration_number, q),
      )
      .map(supplierRowOf);
    return HttpResponse.json(pageOf(rows, params));
  }),
  http.get("*/erp/catalog/suppliers/:id", ({ params }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const state = readErpCatalog();
    const supplier = state.suppliers.find((s) => s.id === params["id"]);
    if (!supplier) return notFound();
    return HttpResponse.json(supplierDetailOf(supplier, who));
  }),
  http.post("*/erp/catalog/suppliers", async ({ request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const data = await body<Partial<SupplierCreate>>(request);
    const name = (data.name ?? "").trim();
    if (!name) return invalid("name", "supplier_name_required");
    if (!data.tin && !data.registration_number?.trim())
      return invalid("tin", "supplier_id_required");
    const state = readErpCatalog();
    if (
      state.suppliers.some(
        (s) =>
          (data.tin && s.tin === data.tin) ||
          (data.registration_number &&
            s.registration_number.toLowerCase() === data.registration_number.trim().toLowerCase()),
      )
    )
      return conflict("supplier_exists", "Такой партнёр уже есть: найдите его в списке.");
    const country = COUNTRIES.find((c) => c.id === data.country_id);
    const supplier: MockSupplier = {
      id: nextId(),
      name,
      tin: data.tin ?? "",
      registration_number: data.registration_number?.trim() ?? "",
      country: country?.name ?? "",
      country_id: country?.id ?? null,
      currency: data.currency ?? null,
      is_manufacturer: data.is_manufacturer ?? false,
      contact_person: data.contact_person ?? "",
      phone: data.phone ?? "",
      email: data.email ?? "",
      website: data.website ?? "",
      legal_address: "",
    };
    state.suppliers.push(supplier);
    return HttpResponse.json(supplierDetailOf(supplier, who), { status: 201 });
  }),
  http.patch("*/erp/catalog/suppliers/:id", async ({ request, params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const supplier = readErpCatalog().suppliers.find((s) => s.id === params["id"]);
    if (!supplier) return notFound();
    const data = await body<SupplierUpdate>(request);
    if (data.name !== undefined) supplier.name = data.name.trim();
    if (data.tin !== undefined) supplier.tin = data.tin;
    if (data.registration_number !== undefined)
      supplier.registration_number = data.registration_number;
    if (data.country_id !== undefined) {
      const country = COUNTRIES.find((c) => c.id === data.country_id);
      supplier.country_id = country?.id ?? null;
      supplier.country = country?.name ?? "";
    }
    if (data.currency !== undefined) supplier.currency = data.currency;
    if (data.contact_person !== undefined) supplier.contact_person = data.contact_person;
    if (data.phone !== undefined) supplier.phone = data.phone;
    if (data.email !== undefined) supplier.email = data.email;
    if (data.website !== undefined) supplier.website = data.website;
    if (data.is_manufacturer !== undefined) supplier.is_manufacturer = data.is_manufacturer;
    if (!supplier.tin && !supplier.registration_number)
      return invalid("tin", "supplier_id_required");
    return HttpResponse.json(supplierDetailOf(supplier, who));
  }),
  http.post("*/erp/catalog/suppliers/:id/offers", async ({ request, params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    if (!who.prices) return erpForbidden("SUPPLIER_PRICES_REQUIRED");
    const state = readErpCatalog();
    const supplier = state.suppliers.find((s) => s.id === params["id"]);
    if (!supplier) return notFound();
    const data = await body<Partial<SupplierOfferCreate>>(request);
    if (!state.items.some((i) => i.id === data.product_id))
      return invalid("product_id", "product_not_found");
    if (!data.price || !DECIMAL.test(data.price.amount))
      return invalid("price", "offer_price_invalid");
    if (state.offers.some((o) => o.supplierId === supplier.id && o.itemId === data.product_id))
      return conflict("offer_exists", "Цена этого партнёра на товар уже есть — измените её.");
    if (data.valid_from && data.valid_until && data.valid_until < data.valid_from)
      return invalid("valid_until", "offer_validity_range_invalid");
    const offer: MockOffer = {
      id: nextId(),
      itemId: data.product_id ?? "",
      supplierId: supplier.id,
      supplier_sku: data.supplier_sku ?? "",
      amount: Number(data.price.amount).toFixed(2),
      currency: data.price.currency,
      quota_qty: data.quota_qty ?? 0,
      min_order_qty: data.min_order_qty ?? 1,
      in_stock_lead_days: data.in_stock_lead_days ?? 0,
      order_lead_days: data.order_lead_days ?? 0,
      stock_status: null,
      valid_from: data.valid_from ?? null,
      valid_until: data.valid_until ?? null,
      is_active: true,
      delivery_basis: data.delivery_basis ?? null,
      lead_time: data.lead_time ?? "",
      source: data.source ?? "manual",
      updated_at: `${MOCK_TODAY}T09:00:00Z`,
      history: [],
    };
    snapshot(offer, who.name);
    state.offers.push(offer);
    return HttpResponse.json(offerOf(offer, true), { status: 201 });
  }),
  http.get("*/erp/catalog/suppliers/:id/offers/:offerId/history", ({ params }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const offer = readErpCatalog().offers.find(
      (o) => o.id === params["offerId"] && o.supplierId === params["id"],
    );
    if (!offer) return notFound();
    return HttpResponse.json({
      items: offer.history.map((h) => ({
        at: h.at,
        price: who.prices ? { amount: h.amount, currency: h.currency } : null,
        valid_from: h.valid_from,
        valid_until: h.valid_until,
        delivery_basis: h.delivery_basis,
        source: h.source,
        by: h.by,
      })),
    });
  }),
  http.patch("*/erp/catalog/suppliers/:id/offers/:offerId", async ({ request, params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const offer = readErpCatalog().offers.find(
      (o) => o.id === params["offerId"] && o.supplierId === params["id"],
    );
    if (!offer) return notFound();
    const data = await body<SupplierOfferUpdate>(request);
    if (data.price !== undefined) {
      if (!who.prices) return erpForbidden("SUPPLIER_PRICES_REQUIRED");
      if (!DECIMAL.test(data.price.amount)) return invalid("price", "offer_price_invalid");
      offer.amount = Number(data.price.amount).toFixed(2);
      offer.currency = data.price.currency;
    }
    if (data.quota_qty !== undefined) offer.quota_qty = data.quota_qty;
    if (data.min_order_qty !== undefined) offer.min_order_qty = data.min_order_qty;
    if (data.in_stock_lead_days !== undefined) offer.in_stock_lead_days = data.in_stock_lead_days;
    if (data.order_lead_days !== undefined) offer.order_lead_days = data.order_lead_days;
    if (data.stock_status !== undefined) offer.stock_status = data.stock_status;
    if (data.valid_from !== undefined) offer.valid_from = data.valid_from;
    if (data.valid_until !== undefined) offer.valid_until = data.valid_until;
    if (data.is_active !== undefined) offer.is_active = data.is_active;
    if (data.delivery_basis !== undefined) offer.delivery_basis = data.delivery_basis;
    if (data.lead_time !== undefined) offer.lead_time = data.lead_time;
    if (data.supplier_sku !== undefined) offer.supplier_sku = data.supplier_sku;
    if (data.source !== undefined) offer.source = data.source;
    if (offer.valid_from && offer.valid_until && offer.valid_until < offer.valid_from)
      return invalid("valid_until", "offer_validity_range_invalid");
    snapshot(offer, who.name);
    return HttpResponse.json(offerOf(offer, who.prices));
  }),

  // --- бригады
  http.get("*/erp/catalog/brigades", ({ request }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const params = new URL(request.url).searchParams;
    const q = params.get("q");
    const kind = params.get("kind");
    const inactive = params.get("include_inactive") === "true";
    const rows = readErpCatalog()
      .brigades.filter(
        (b) =>
          (inactive || b.is_active) &&
          (!kind || b.kind === kind) &&
          (contains(b.name, q) || contains(b.specialization, q)),
      )
      .map((b) => brigadeOf(b, who));
    return HttpResponse.json(pageOf(rows, params));
  }),
  http.post("*/erp/catalog/brigades", async ({ request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const data = await body<Partial<BrigadeCreate>>(request);
    if (!data.name?.trim()) return invalid("name", "brigade_name_required");
    if (data.rate && !who.rates) return erpForbidden("CREW_RATES_REQUIRED");
    const brigade: MockBrigade = {
      id: nextId(),
      name: data.name.trim(),
      kind: data.kind ?? "brigade",
      specialization: data.specialization ?? "",
      headcount: data.headcount ?? 1,
      rate: data.rate
        ? {
            amount: Number(data.rate.amount).toFixed(2),
            currency: data.rate.currency,
            unit: data.rate_unit ?? "day",
          }
        : null,
      note: data.note ?? "",
      is_active: data.is_active ?? true,
    };
    readErpCatalog().brigades.push(brigade);
    return HttpResponse.json(brigadeOf(brigade, who), { status: 201 });
  }),
  http.patch("*/erp/catalog/brigades/:id", async ({ request, params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const brigade = readErpCatalog().brigades.find((b) => b.id === params["id"]);
    if (!brigade) return notFound();
    const data = await body<BrigadeUpdate>(request);
    if ((data.rate !== undefined || data.rate_unit !== undefined) && !who.rates)
      return erpForbidden("CREW_RATES_REQUIRED");
    if (data.name !== undefined) {
      if (!data.name.trim()) return invalid("name", "brigade_name_required");
      brigade.name = data.name.trim();
    }
    if (data.kind !== undefined) brigade.kind = data.kind;
    if (data.specialization !== undefined) brigade.specialization = data.specialization;
    if (data.headcount !== undefined) brigade.headcount = data.headcount;
    if (data.note !== undefined) brigade.note = data.note;
    if (data.is_active !== undefined) brigade.is_active = data.is_active;
    if (data.rate !== undefined) {
      brigade.rate = data.rate
        ? {
            amount: Number(data.rate.amount).toFixed(2),
            currency: data.rate.currency,
            unit: data.rate_unit ?? brigade.rate?.unit ?? "day",
          }
        : null;
    } else if (data.rate_unit !== undefined && brigade.rate) {
      brigade.rate = { ...brigade.rate, unit: data.rate_unit };
    }
    return HttpResponse.json(brigadeOf(brigade, who));
  }),

  // --- запросы на категории (состояние общее с Admin · Компания)
  http.get("*/erp/catalog/category-requests", ({ request }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const status = new URL(request.url).searchParams.get("status");
    return HttpResponse.json({
      items: readCompanyMock().requests.filter((r) => !status || r.status === status),
    });
  }),
  http.post("*/erp/catalog/category-requests", async ({ request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const data = await body<Partial<CategoryProposalIn>>(request);
    const name = (data.name ?? "").trim();
    if (!name) return invalid("name", "category_request_name_required");
    const created = updateCompanyMock((state): CategoryRequest | Response => {
      if (
        state.requests.some(
          (r) => r.status === "pending" && r.proposed_name.toLowerCase() === name.toLowerCase(),
        )
      )
        return conflict("already_pending", "Запрос на такую категорию уже на рассмотрении.");
      const parent = state.categories.find((c) => c.id === data.parent_id);
      const row: CategoryRequest = {
        id: String(state.nextId++),
        proposed_name: name,
        ...(parent ? { parent_name: parent.name } : {}),
        ...(data.justification?.trim() ? { justification: data.justification.trim() } : {}),
        status: "pending",
        company_name: state.company.name,
        requested_by: who.email,
        created_at: `${MOCK_TODAY}T09:00:00.000Z`,
      };
      state.requests.unshift(row);
      return row;
    });
    return created instanceof Response ? created : HttpResponse.json(created, { status: 201 });
  }),

  // --- справочники
  http.get("*/erp/catalog/exchange-rates", ({ request }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const params = new URL(request.url).searchParams;
    const currency = params.get("currency")?.toUpperCase();
    const state = readErpCatalog();
    // Курс, введённый в Admin · Компания, показывается и здесь.
    const manual = readCompanyMock().fx.journal.filter((j) => j.kind === "manual");
    const extra = manual
      .filter(
        (j) =>
          !state.rates.some(
            (r) => r.currency === "USD" && r.rate_date === j.rate_date && r.source === "MANUAL",
          ),
      )
      .map((j) => ({
        id: `m${j.id}`,
        currency: "USD",
        rate_to_uzs: j.rate_to_uzs,
        rate_date: j.rate_date,
        source: "MANUAL" as const,
      }));
    const rows = [...state.rates, ...extra]
      .filter((r) => !currency || r.currency === currency)
      .sort(
        (a, b) => b.rate_date.localeCompare(a.rate_date) || a.currency.localeCompare(b.currency),
      );
    return HttpResponse.json(pageOf(rows, params));
  }),
  http.get("*/erp/catalog/hs-codes", ({ request }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const params = new URL(request.url).searchParams;
    const q = params.get("q");
    const level = params.get("level");
    const rows = readErpCatalog().hs.filter(
      (c) =>
        (!q || c.code.startsWith(q.trim()) || contains(c.name, q)) &&
        (!level || c.level === Number(level)) &&
        (params.get("active") !== "true" || c.is_active),
    );
    return HttpResponse.json(pageOf(rows, params));
  }),
  http.post("*/erp/catalog/hs-codes", async ({ request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const data = await body<Partial<HsCodeCreate>>(request);
    const code = data.code ?? "";
    const name = (data.name ?? "").trim();
    if (!/^\d{2}$|^\d{4}$|^\d{6}$|^\d{8}$|^\d{10}$/.test(code))
      return invalid("code", "hs_code_invalid");
    if (!name) return invalid("name", "hs_name_required");
    const state = readErpCatalog();
    if (state.hs.some((c) => c.code === code))
      return conflict("hs_code_exists", "Такой код ТН ВЭД уже есть в справочнике.");
    const row: HsCode = {
      id: nextId(),
      code,
      name,
      unit_name: data.unit_name ?? "",
      extra_unit_name: data.extra_unit_name ?? "",
      level: code.length as HsCode["level"],
      valid_from: data.valid_from ?? null,
      valid_until: data.valid_until ?? null,
      is_active: !data.valid_until || data.valid_until >= MOCK_TODAY,
      source: "вручную",
    };
    state.hs.push(row);
    state.hs.sort((a, b) => a.code.localeCompare(b.code));
    return HttpResponse.json(row, { status: 201 });
  }),
  http.patch("*/erp/catalog/hs-codes/:id", async ({ request, params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const row = readErpCatalog().hs.find((c) => c.id === params["id"]);
    if (!row) return notFound();
    const data = await body<HsCodeUpdate>(request);
    if (data.name !== undefined) {
      if (!data.name.trim()) return invalid("name", "hs_name_required");
      row.name = data.name.trim();
    }
    if (data.unit_name !== undefined) row.unit_name = data.unit_name;
    if (data.extra_unit_name !== undefined) row.extra_unit_name = data.extra_unit_name;
    if (data.valid_from !== undefined) row.valid_from = data.valid_from;
    if (data.valid_until !== undefined) row.valid_until = data.valid_until;
    if (row.valid_from && row.valid_until && row.valid_until < row.valid_from)
      return invalid("valid_until", "hs_validity_range_invalid");
    row.is_active = !row.valid_until || row.valid_until >= MOCK_TODAY;
    return HttpResponse.json(row);
  }),
  http.get("*/erp/catalog/manufacturers", ({ request }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const params = new URL(request.url).searchParams;
    const inactive = params.get("include_inactive") === "true" && who.full;
    const rows = readErpCatalog().manufacturers.filter(
      (m) => (inactive || m.is_active) && contains(m.name, params.get("q")),
    );
    return HttpResponse.json(pageOf(rows, params));
  }),
  http.post("*/erp/catalog/manufacturers", async ({ request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const data = await body<Partial<ManufacturerCreate>>(request);
    const name = (data.name ?? "").trim();
    if (!name) return invalid("name", "name_required");
    const state = readErpCatalog();
    if (state.manufacturers.some((m) => m.name.toLowerCase() === name.toLowerCase()))
      return conflict("manufacturer_exists", "Такой производитель уже есть в справочнике.");
    const country = COUNTRIES.find((c) => c.id === data.country_id);
    const row: Manufacturer = {
      id: nextId(),
      name,
      country_id: country?.id ?? null,
      country_name: country?.name ?? null,
      website: data.website ?? "",
      is_active: data.is_active ?? true,
      company_id: data.company_id ?? null,
    };
    state.manufacturers.push(row);
    return HttpResponse.json(row, { status: 201 });
  }),
  http.patch("*/erp/catalog/manufacturers/:id", async ({ request, params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const row = readErpCatalog().manufacturers.find((m) => m.id === params["id"]);
    if (!row) return notFound();
    const data = await body<ManufacturerUpdate>(request);
    if (data.name !== undefined) {
      if (!data.name.trim()) return invalid("name", "name_required");
      row.name = data.name.trim();
    }
    if (data.country_id !== undefined) {
      const country = COUNTRIES.find((c) => c.id === data.country_id);
      row.country_id = country?.id ?? null;
      row.country_name = country?.name ?? null;
    }
    if (data.website !== undefined) row.website = data.website;
    if (data.is_active !== undefined) row.is_active = data.is_active;
    if (data.company_id !== undefined) row.company_id = data.company_id;
    return HttpResponse.json(row);
  }),

  // --- техдокументация
  http.get("*/erp/docs/files", ({ request }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const params = new URL(request.url).searchParams;
    const q = params.get("q");
    const rows = readErpCatalog()
      .docs.map((d) => d.doc)
      .filter(
        (d) =>
          (contains(d.title, q) ||
            contains(d.original_name, q) ||
            contains(d.product?.name ?? "", q)) &&
          (!params.get("kind") || d.kind === params.get("kind")) &&
          (!params.get("product_id") || d.product?.id === params.get("product_id")) &&
          (!params.get("deal_id") || d.dealId === params.get("deal_id")) &&
          (!params.get("review_state") || d.review_state === params.get("review_state")),
      )
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .map(docOf);
    return HttpResponse.json(pageOf(rows, params));
  }),
  http.post("*/erp/docs/files", async ({ request }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const form = await parseUpload(request);
    const file = form?.file;
    if (!form || !file) return invalid("file", "no_file_provided");
    const name = file.name;
    const ext = name.slice(name.lastIndexOf(".")).toLowerCase();
    if (![".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".xls", ".xlsx"].includes(ext))
      return invalid("file", "file_type_not_allowed");
    if (file.bytes.length > 20 * 1024 * 1024)
      return failure(413, "PAYLOAD_TOO_LARGE", "Файл больше 20 МБ.", "bff", {
        max_bytes: 20 * 1024 * 1024,
      });
    const productId = form.fields["product_id"] || null;
    const dealId = form.fields["deal_id"] || null;
    if (!productId && !dealId) return invalid("product_id", "tech_doc_link_required");
    const kind = form.fields["kind"] || "other";
    if (!DOC_KINDS.some((k) => k.code === kind)) return invalid("kind", "tech_doc_kind_invalid");
    const issuedAt = form.fields["issued_at"] || null;
    const validUntil = form.fields["valid_until"] || null;
    if (issuedAt && validUntil && validUntil < issuedAt)
      return invalid("valid_until", "tech_doc_validity_range_invalid");
    const bytes = file.bytes;
    const type =
      ext === ".pdf"
        ? "application/pdf"
        : ext === ".png"
          ? "image/png"
          : ext === ".jpg" || ext === ".jpeg"
            ? "image/jpeg"
            : file.type || "application/octet-stream";
    const doc = {
      id: nextId(),
      kind,
      kind_name: kindName(kind),
      number: (form.fields["number"] ?? "").trim(),
      issued_by: (form.fields["issued_by"] ?? "").trim(),
      issued_at: issuedAt,
      valid_until: validUntil,
      is_expired: validUntil !== null && validUntil < MOCK_TODAY,
      client_visible:
        form.fields["client_visible"] !== undefined
          ? form.fields["client_visible"] === "true"
          : DOC_KINDS.some((k) => k.code === kind && k.client_visible_default),
      review_state: "approved" as const,
      partner: null,
      title: (form.fields["title"] ?? "").trim() || name.replace(/\.[^.]+$/, ""),
      original_name: name,
      content_type: type,
      size_bytes: bytes.length,
      previewable: ["application/pdf", "image/png", "image/jpeg"].includes(type),
      product: productId ? productRef(productId) : null,
      dealId,
      uploaded_by: who.name,
      created_at: `${MOCK_TODAY}T10:00:00Z`,
    };
    readErpCatalog().docs.unshift({ doc, bytes });
    return HttpResponse.json(docOf(doc), { status: 201 });
  }),
  http.patch("*/erp/docs/files/:id", async ({ request, params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const found = readErpCatalog().docs.find((d) => d.doc.id === params["id"]);
    if (!found) return notFound();
    const data = await body<TechDocUpdate>(request);
    const doc = found.doc;
    if (data.kind !== undefined) {
      if (!DOC_KINDS.some((k) => k.code === data.kind))
        return invalid("kind", "tech_doc_kind_invalid");
      doc.kind = data.kind;
      doc.kind_name = kindName(data.kind);
    }
    if (data.title !== undefined && data.title.trim()) doc.title = data.title.trim();
    if (data.number !== undefined) doc.number = data.number.trim();
    if (data.issued_by !== undefined) doc.issued_by = data.issued_by.trim();
    if (data.issued_at !== undefined) doc.issued_at = data.issued_at;
    if (data.valid_until !== undefined) doc.valid_until = data.valid_until;
    if (data.client_visible !== undefined) doc.client_visible = data.client_visible;
    if (doc.issued_at && doc.valid_until && doc.valid_until < doc.issued_at)
      return invalid("valid_until", "tech_doc_validity_range_invalid");
    doc.is_expired = doc.valid_until !== null && doc.valid_until < MOCK_TODAY;
    return HttpResponse.json(docOf(doc));
  }),
  http.post("*/erp/docs/files/:id/review", async ({ request, params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const found = readErpCatalog().docs.find((d) => d.doc.id === params["id"]);
    if (!found) return notFound();
    const data = await body<TechDocReview>(request);
    const doc = found.doc;
    if (doc.review_state !== "pending")
      return failure(409, "TECH_DOC_NOT_PENDING", "Решение по документу уже принято.", "erp");
    if (data.decision === "approve") {
      doc.review_state = "approved";
      doc.client_visible =
        data.client_visible ??
        DOC_KINDS.some((k) => k.code === doc.kind && k.client_visible_default);
    } else {
      doc.review_state = "rejected";
      doc.client_visible = false;
    }
    return HttpResponse.json(docOf(doc));
  }),
  http.delete("*/erp/docs/files/:id", ({ params }) => {
    const who = guard("full");
    if (isResponse(who)) return who;
    const state = readErpCatalog();
    const index = state.docs.findIndex((d) => d.doc.id === params["id"]);
    if (index < 0) return notFound();
    state.docs.splice(index, 1);
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("*/erp/docs/files/:id/content", ({ params }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const found = readErpCatalog().docs.find((d) => d.doc.id === params["id"]);
    if (!found) return notFound();
    return new HttpResponse(found.bytes, {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": `attachment; filename="${found.doc.original_name}"`,
        "X-Content-Type-Options": "nosniff",
      },
    });
  }),
  http.get("*/erp/docs/deals", ({ request }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const q = (new URL(request.url).searchParams.get("q") ?? "").trim().toLowerCase();
    const items = DEALS.filter(
      (d) =>
        !q ||
        dealNumber(d).toLowerCase().includes(q.replace(/^zv/, "зв").replace(/^pr/, "пр")) ||
        d.title.toLowerCase().includes(q) ||
        d.company.toLowerCase().includes(q),
    ).map((d) => ({
      erp_deal_id: d.id,
      number: dealNumber(d),
      title: d.title,
      company: d.company,
    }));
    return HttpResponse.json({ items, sources: { crm: "ok", erp: "ok" } });
  }),
];

function docOf(doc: MockDoc["doc"]): TechDoc {
  const deal = DEALS.find((d) => String(d.id) === doc.dealId);
  return {
    ...docRefOf(doc),
    content_type: doc.content_type,
    size_bytes: doc.size_bytes,
    previewable: doc.previewable,
    product: doc.product,
    deal: deal
      ? { id: String(deal.id), number: dealNumber(deal), title: deal.title, client: deal.company }
      : null,
    uploaded_by: doc.uploaded_by,
    created_at: doc.created_at,
  };
}
