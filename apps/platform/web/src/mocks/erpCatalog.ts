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
  CategoryProposalIn,
  CategoryRequest,
  HsCode,
  HsCodeCreate,
  HsCodeUpdate,
  Manufacturer,
  ManufacturerCreate,
  ManufacturerUpdate,
  SupplierDetail,
  SupplierOfferUpdate,
  SupplierRow,
  TechDoc,
  TechDocKind,
} from "../shared/api/generated/model";
import {
  COUNTRIES,
  CURRENCIES,
  DEALS,
  MOCK_TODAY,
  type MockBrigade,
  type MockItem,
  type MockDoc,
  type MockOffer,
  type MockSupplier,
  UNITS,
  dealNumber,
  nextId,
  productRef,
  readErpCatalog,
  validityOf,
} from "./fixtures/erpCatalog";
import { readCompanyMock, updateCompanyMock } from "./fixtures/company";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки «Расчёт · Номенклатура и поставщики» и «Техдокументация» (D2-3, BFF 0.26.0). Права — как в BFF: раздел `erp.stock`
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
  };
}

function offerOf(offer: MockOffer, prices: boolean): CatalogOffer {
  const state = readErpCatalog();
  const supplier = state.suppliers.find((s) => s.id === offer.supplierId);
  const product = productRef(offer.itemId);
  if (!supplier || !product) throw new Error(`предложение ${offer.id} без поставщика или позиции`);
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
    valid_from: offer.valid_from,
    valid_until: offer.valid_until,
    is_active: offer.is_active,
    validity: validityOf(offer.valid_until),
  };
}

function detailOf(item: MockItem, who: Caller): CatalogItemDetail {
  const state = readErpCatalog();
  return {
    ...rowOf(item),
    description: item.description,
    gost_drawing: item.gost_drawing,
    hs_code: item.hs_code,
    manufacturer_part_number: "",
    brand: item.brand,
    offers: state.offers.filter((o) => o.itemId === item.id).map((o) => offerOf(o, who.prices)),
    prices_visible: who.prices,
    tech_docs: state.docs
      .filter((d) => d.doc.product?.id === item.id)
      .map((d) => ({ id: d.doc.id, title: d.doc.title, kind: d.doc.kind })),
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
    country: supplier.country,
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
    if (filename !== undefined && field === "file") {
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

export const erpCatalogHandlers = [
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
    const rows = readErpCatalog()
      .items.filter(
        (i) =>
          (contains(i.name, q) || contains(i.sku, q) || contains(i.gost_drawing, q)) &&
          (!kind || i.kind === kind) &&
          (!category || i.categoryId === category),
      )
      .map(rowOf);
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
      description: data.description ?? "",
      gost_drawing: "",
      hs_code: "",
      brand: null,
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
    return HttpResponse.json(detailOf(item, who));
  }),

  // --- поставщики
  http.get("*/erp/catalog/suppliers", ({ request }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const params = new URL(request.url).searchParams;
    const q = params.get("q");
    const rows = readErpCatalog()
      .suppliers.filter((s) => contains(s.name, q) || contains(s.tin, q))
      .map(supplierRowOf);
    return HttpResponse.json(pageOf(rows, params));
  }),
  http.get("*/erp/catalog/suppliers/:id", ({ params }) => {
    const who = guard("read");
    if (isResponse(who)) return who;
    const state = readErpCatalog();
    const supplier = state.suppliers.find((s) => s.id === params["id"]);
    if (!supplier) return notFound();
    const detail: SupplierDetail = {
      ...supplierRowOf(supplier),
      contact_person: supplier.contact_person,
      phone: supplier.phone,
      email: supplier.email,
      website: supplier.website,
      legal_address: supplier.legal_address,
      offers: state.offers
        .filter((o) => o.supplierId === supplier.id)
        .map((o) => offerOf(o, who.prices)),
      prices_visible: who.prices,
    };
    return HttpResponse.json(detail);
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
    if (offer.valid_from && offer.valid_until && offer.valid_until < offer.valid_from)
      return invalid("valid_until", "offer_validity_range_invalid");
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
          (!params.get("deal_id") || d.dealId === params.get("deal_id")),
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
    const kind = (form.fields["kind"] || "other") as TechDocKind;
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
    id: doc.id,
    kind: doc.kind,
    title: doc.title,
    original_name: doc.original_name,
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
