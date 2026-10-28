import { HttpResponse, http } from "msw";

import type {
  CalcSheet,
  Me,
  PriceRequest,
  PriceRequestAnswerIn,
  PriceRequestIn,
  PriceRequestList,
  QueueItem,
  StockAdjustIn,
  StockBalanceList,
  StockProduct,
  StockReceipts,
  StockRequestRef,
  StockReservation,
  StockReservationList,
  StockReserveIn,
  StockRow,
  StockShipIn,
  StockShipment,
  StockShipmentList,
  StockSupplierList,
  SupplierOrderCancelIn,
  SupplierOrderConfirmIn,
  SupplierOrderCreate,
  SupplierOrderDetail,
  SupplierOrderFromRequest,
  SupplierOrderList,
  SupplierOrderPatch,
  SupplierOrderReceiptIn,
  SupplierOrderRow,
  SupplierOrderSendIn,
} from "../shared/api/generated/model";
import { CATALOG } from "./fixtures/calc";
import {
  type MockOrder,
  type MockOrderLog,
  type MockProduct,
  type MockReservation,
  type MockStock,
  REQUESTS,
  SUPPLIERS,
  seedStock,
} from "./fixtures/stock";
import {
  calcLineIds,
  calcSheetByNumber,
  canZone,
  failure,
  fields,
  guard,
  level,
  lookupCalcLine,
} from "./erpCalc";

/**
 * Моки «Склада» (D2-2, BFF 0.27.0) — поведение BFF и ERP вместе: доступ по разделу `erp.stock` (чтение — `read`, действия —
 * `full`), свободный остаток = остаток − резервы, резерв строки один и не больше свободного, заказ поставщику идёт
 * черновик → отправлен → подтверждён → получен (недопустимый переход — 409 `transition_not_allowed`), «Отправить» пишет
 * письмо в журнал заказа, приёмка растит остаток и резервирует под проект, отгрузка уменьшает остаток и резерв, цены
 * поставщика — группе `supplier_prices`/`cost_margin` или держателю `erp.calc.goods`. Состояние — в `localStorage`.
 */
const KEY = "rt-pf-mock-stock-v1";
let memory: MockStock | null = null;

function read(): MockStock {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as MockStock;
  } catch {
    // Хранилище недоступно — состояние в памяти.
  }
  memory ??= seedStock();
  return memory;
}

function write(state: MockStock): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Только в памяти.
  }
}

/** Для тестов: исходные остатки, резервы и заказы. */
export function resetStockMock(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // нечего удалять
  }
}

const seg = (value: string) => encodeURIComponent(value);
const today = () => new Date().toISOString().slice(0, 10);
const money = (value: number) => value.toFixed(2);

const conflict = (reason: string, message: string, extra: Record<string, unknown> = {}) =>
  failure(409, "CONFLICT", message, { source: "erp", reason, ...extra });
const missing = (reason: string, message: string) =>
  failure(404, "NOT_FOUND", message, { source: "erp", reason });

function pricesVisible(user: Me): boolean {
  const held = fields(user);
  return held.has("supplier_prices") || held.has("cost_margin") || canZone(user, "goods");
}

const rights = (user: Me) => ({
  manage: level(user, "erp.stock") === "full",
  ship: level(user, "erp.stock") === "full",
});

// --- остатки ------------------------------------------------------------------------------------

const onHandOf = (product: MockProduct) => product.cells.reduce((sum, c) => sum + c.onHand, 0);

function remaining(r: MockReservation): number {
  return r.status === "active" ? r.quantity - r.shipped : 0;
}

function reservedOf(state: MockStock, productId: number): number {
  return state.reservations
    .filter((r) => r.productId === productId)
    .reduce((sum, r) => sum + remaining(r), 0);
}

function incomingOf(
  state: MockStock,
  productId: number,
): { quantity: number; next: string | null } {
  let quantity = 0;
  let next: string | null = null;
  for (const order of state.orders) {
    if (order.status !== "sent" && order.status !== "confirmed") continue;
    for (const line of order.lines) {
      if (line.productId !== productId || line.quantity <= line.received) continue;
      quantity += line.quantity - line.received;
      if (order.expectedDate && (next === null || order.expectedDate < next)) {
        next = order.expectedDate;
      }
    }
  }
  return { quantity, next };
}

function mainCell(product: MockProduct): string | null {
  const best = [...product.cells].sort((a, b) => b.onHand - a.onHand).find((c) => c.onHand > 0);
  return best?.cell ?? null;
}

/** Склад строки расчёта: общий для `erpCalc` и экрана «Склад», чтобы резерв из расчёта был виден в обоих. */
export function stockOfLine(
  productId: number | null,
  lineId: number,
): {
  onHand: number;
  free: number;
  reserved: number;
  cell: string | null;
  available: number;
} | null {
  if (productId === null) return null;
  const state = read();
  const product = state.products.find((p) => p.id === productId);
  if (!product) return null;
  const onHand = onHandOf(product);
  const reservedAll = reservedOf(state, productId);
  const mine = state.reservations
    .filter((r) => r.lineId === lineId && r.status === "active")
    .reduce((sum, r) => sum + remaining(r), 0);
  return {
    onHand,
    free: Math.max(onHand - reservedAll, 0),
    reserved: mine,
    cell: mainCell(product),
    available: Math.max(onHand - reservedAll, 0) + mine,
  };
}

function refOf(number: string): StockRequestRef {
  const known = REQUESTS.find((r) => r.number === number);
  return {
    number,
    client: known?.client ?? null,
    path: number.startsWith("ПР") ? `/eds/projects/${seg(number)}` : `/erp/calc/${seg(number)}`,
  };
}

function rowOf(state: MockStock, product: MockProduct): StockRow {
  const onHand = onHandOf(product);
  const reserved = reservedOf(state, product.id);
  const incoming = incomingOf(state, product.id);
  return {
    product_id: String(product.id),
    name: product.name,
    article: product.article,
    unit: product.unit,
    on_hand: onHand,
    reserved,
    free: Math.max(onHand - reserved, 0),
    incoming: incoming.quantity,
    next_expected: incoming.next,
    cells: product.cells
      .filter((c) => c.onHand > 0)
      .map((c) => ({ cell: c.cell, on_hand: c.onHand })),
  };
}

function presentReservation(state: MockStock, r: MockReservation): StockReservation {
  const product = state.products.find((p) => p.id === r.productId);
  return {
    id: String(r.id),
    product_id: String(r.productId),
    product_name: product?.name ?? "Товар",
    request: refOf(r.request),
    line_id: r.lineId === null ? null : String(r.lineId),
    quantity: r.quantity,
    shipped_quantity: r.shipped,
    remaining: remaining(r),
    status: r.status,
    created_at: r.createdAt,
    created_by: r.createdBy,
  };
}

function presentProduct(state: MockStock, product: MockProduct, user: Me): StockProduct {
  const incoming = state.orders
    .filter((o) => o.status === "sent" || o.status === "confirmed")
    .flatMap((o) =>
      o.lines
        .filter((l) => l.productId === product.id && l.quantity > l.received)
        .map((l) => ({
          number: o.number,
          status: o.status,
          supplier: SUPPLIERS.find((s) => s.id === o.supplierId)?.name ?? "—",
          expected_date: o.expectedDate,
          quantity_left: l.quantity - l.received,
          path: `/erp/stock/${seg(o.number)}`,
        })),
    );
  return {
    ...rowOf(state, product),
    reservations: state.reservations
      .filter((r) => r.productId === product.id && r.status === "active")
      .map((r) => presentReservation(state, r)),
    incoming_orders: incoming,
    movements: state.movements
      .filter((m) => m.productId === product.id)
      .slice(-30)
      .reverse()
      .map((m) => ({
        kind: m.kind,
        quantity: m.quantity,
        cell: m.cell,
        at: m.at,
        by: m.by,
        note: m.note,
      })),
    rights: rights(user),
  };
}

// --- заказы -------------------------------------------------------------------------------------

const overdueDays = (order: MockOrder): number | null => {
  if (!order.expectedDate || (order.status !== "sent" && order.status !== "confirmed")) return null;
  const diff = Math.floor((Date.parse(today()) - Date.parse(order.expectedDate)) / 86_400_000);
  return diff > 0 ? diff : null;
};

function actionsOf(order: MockOrder, user: Me) {
  const manage = level(user, "erp.stock") === "full";
  const live = order.status === "draft" || order.status === "sent" || order.status === "confirmed";
  const touched = order.lines.some((l) => l.received > 0);
  return {
    edit: manage && order.status === "draft",
    send: manage && order.status === "draft",
    confirm: manage && order.status === "sent",
    receive: manage && order.status === "confirmed",
    cancel: manage && live && !touched,
  };
}

function orderRow(order: MockOrder, user: Me): SupplierOrderRow {
  const supplier = SUPPLIERS.find((s) => s.id === order.supplierId);
  const quantity = order.lines.reduce((sum, l) => sum + l.quantity, 0);
  const received = order.lines.reduce((sum, l) => sum + l.received, 0);
  const days = overdueDays(order);
  const prices = pricesVisible(user);
  const priced = order.lines.some((l) => l.unitPrice !== null);
  const requests = [
    ...new Set(order.lines.map((l) => l.request).filter((r): r is string => r !== null)),
  ].map(refOf);
  return {
    number: order.number,
    status: order.status,
    supplier: { id: String(order.supplierId), name: supplier?.name ?? "Поставщик", email: null },
    expected_date: order.expectedDate,
    overdue: days !== null,
    days_overdue: days,
    currency: order.currency,
    lines_count: order.lines.length,
    quantity,
    received_quantity: received,
    receipt_state: received === 0 ? "none" : received >= quantity ? "full" : "partial",
    total:
      prices && priced
        ? money(order.lines.reduce((sum, l) => sum + Number(l.unitPrice ?? 0) * l.quantity, 0))
        : null,
    requests,
    created_at: order.createdAt,
    created_by: order.createdBy,
    actions: actionsOf(order, user),
    path: `/erp/stock/${seg(order.number)}`,
  };
}

function presentOrder(state: MockStock, order: MockOrder, user: Me): SupplierOrderDetail {
  const prices = pricesVisible(user);
  const supplier = SUPPLIERS.find((s) => s.id === order.supplierId);
  const row = orderRow(order, user);
  return {
    ...row,
    supplier: { ...row.supplier, email: supplier?.email ?? null },
    note: order.note,
    sent_at: order.sentAt,
    sent_to: order.sentTo,
    confirmed_at: order.confirmedAt,
    received_at: order.receivedAt,
    cancelled_at: order.cancelledAt,
    cancel_reason: order.cancelReason,
    lines: order.lines.map((l, index) => ({
      id: String(l.id),
      position: index + 1,
      product_id: String(l.productId),
      name: l.name,
      article: l.article,
      unit: l.unit,
      quantity: l.quantity,
      received_quantity: l.received,
      unit_price: prices ? l.unitPrice : null,
      line_total: prices && l.unitPrice !== null ? money(Number(l.unitPrice) * l.quantity) : null,
      request: l.request ? refOf(l.request) : null,
      line_id: l.lineId === null ? null : String(l.lineId),
    })),
    receipts: state.receipts
      .filter((r) => r.orderNumber === order.number)
      .map((r) => ({
        id: String(r.id),
        received_at: r.receivedAt,
        received_by: r.receivedBy,
        supplier_doc: r.supplierDoc,
        note: r.note,
        lines: r.lines.map((l) => ({
          order_line_id: String(l.orderLineId),
          name: l.name,
          quantity: l.quantity,
          cell: l.cell,
        })),
      })),
    log: order.log.map((e) => ({ kind: e.kind, at: e.at, by: e.by, detail: e.detail })),
    rights: { ...rights(user), prices },
  };
}

function findOrder(state: MockStock, number: string): MockOrder | undefined {
  return state.orders.find((o) => o.number === decodeURIComponent(number));
}

const orderMissing = () => missing("order_not_found", "Заказа с таким номером нет.");
const log = (
  order: MockOrder,
  user: Me,
  kind: MockOrderLog["kind"],
  detail: string | null = null,
) => {
  order.log.push({ kind, at: new Date().toISOString(), by: user.name, detail });
};

function transitionError(order: MockOrder) {
  return conflict("transition_not_allowed", "Заказ уже в другом статусе: обновите экран.", {
    current: order.status,
  });
}

function reserveFor(
  state: MockStock,
  user: Me,
  lineNumber: string,
  lineId: number,
  quantity: number,
) {
  const calcLine = lookupCalcLine(lineNumber, lineId);
  if (!calcLine) return missing("line_not_found", "Строки нет.");
  if (calcLine.productId === null) {
    return conflict("product_required", "Сначала сопоставьте строку с карточкой каталога.");
  }
  const product = state.products.find((p) => p.id === calcLine.productId);
  if (!product) return conflict("product_required", "Товара нет на складе.");
  const current = state.reservations.find((r) => r.lineId === lineId && r.status === "active");
  const free =
    Math.max(onHandOf(product) - reservedOf(state, product.id), 0) +
    (current ? remaining(current) : 0);
  if (quantity > calcLine.quantity) {
    return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", {
      source: "erp",
      reason: "quantity_out_of_range",
      fields: ["quantity"],
      max: calcLine.quantity,
    });
  }
  if (quantity > free) {
    return conflict("not_enough_stock", "Столько свободного товара на складе нет.", { free });
  }
  if (current) {
    current.quantity = quantity;
  } else {
    state.nextId += 1;
    state.reservations.push({
      id: state.nextId,
      productId: product.id,
      request: lineNumber,
      lineId,
      quantity,
      shipped: 0,
      status: "active",
      createdAt: new Date().toISOString(),
      createdBy: user.name,
    });
  }
  return null;
}

const addMovement = (
  state: MockStock,
  user: Me,
  productId: number,
  kind: "receipt" | "shipment" | "adjustment",
  quantity: number,
  cell: string | null,
  note: string | null,
) => {
  state.movements.push({
    productId,
    kind,
    quantity,
    cell,
    at: new Date().toISOString(),
    by: user.name,
    note,
  });
};

function addToCell(product: MockProduct, cell: string | null, quantity: number): boolean {
  const target = product.cells.find((c) => c.cell === cell);
  if (target) {
    if (target.onHand + quantity < 0) return false;
    target.onHand += quantity;
    return true;
  }
  if (quantity < 0) return false;
  product.cells.push({ cell, onHand: quantity });
  return true;
}

/** Очередь «Моих задач»: просроченные заказы поставщикам — тем, у кого `erp.stock` полный (вид `supplier_overdue`). */
export function stockQueueItems(
  view: readonly { id: string; access: Partial<Record<string, string>> }[],
): QueueItem[] {
  const full = view.find((r) => r.access["erp.stock"] === "full");
  if (!full) return [];
  return read()
    .orders.filter((o) => overdueDays(o) !== null)
    .map((o): QueueItem => {
      const supplier = SUPPLIERS.find((s) => s.id === o.supplierId)?.name ?? null;
      const days = overdueDays(o) ?? 0;
      return {
        id: `supplier_order:${String(o.id)}`,
        role_id: full.id,
        kind: "supplier_overdue",
        title: `Просрочен заказ ${o.number}`,
        subtitle: [supplier, `${String(days)} дн. просрочки`].filter(Boolean).join(" · "),
        due_label: "overdue",
        due_at: new Date(`${o.expectedDate ?? today()}T18:59:59Z`).toISOString(),
        object: {
          kind: "supplier_order",
          number: o.number,
          ...(supplier ? { title: supplier } : {}),
          path: `/erp/stock/${seg(o.number)}`,
        },
      };
    });
}

export const erpStockHandlers = [
  http.get("*/api/v1/erp/stock/balances", ({ request }) => {
    const held = guard("erp.stock", "read");
    if ("error" in held) return held.error;
    const state = read();
    const params = new URL(request.url).searchParams;
    const words = (params.get("q") ?? "").toLowerCase().split(/\s+/).filter(Boolean);
    const only = params.get("only");
    const products = state.products.filter((p) => {
      if (words.length)
        return words.every((w) => `${p.name} ${p.article}`.toLowerCase().includes(w));
      const row = rowOf(state, p);
      return row.on_hand > 0 || row.reserved > 0 || row.incoming > 0;
    });
    const items = products
      .map((p) => rowOf(state, p))
      .filter((row) =>
        only === "reserved" ? row.reserved > 0 : only === "incoming" ? row.incoming > 0 : true,
      );
    return HttpResponse.json<StockBalanceList>({ items, rights: rights(held.user) });
  }),

  http.get("*/api/v1/erp/stock/balances/:product", ({ params }) => {
    const held = guard("erp.stock", "read");
    if ("error" in held) return held.error;
    const state = read();
    const product = state.products.find((p) => String(p.id) === String(params["product"]));
    return product
      ? HttpResponse.json<StockProduct>(presentProduct(state, product, held.user))
      : missing("product_not_found", "Товара нет.");
  }),

  http.post("*/api/v1/erp/stock/adjustments", async ({ request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json()) as StockAdjustIn;
    const state = read();
    let product = state.products.find((p) => String(p.id) === body.product_id);
    if (!product) {
      const known = CATALOG.find((c) => String(c.id) === body.product_id && c.kind === "goods");
      if (!known) return missing("product_not_found", "Товара нет.");
      product = { id: known.id, name: known.name, article: known.article, unit: "шт.", cells: [] };
      state.products.push(product);
    }
    if (body.quantity === 0) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", {
        source: "erp",
        reason: "quantity_required",
        fields: ["quantity"],
      });
    }
    const onHand = onHandOf(product);
    if (body.quantity < 0 && onHand + body.quantity < 0) {
      return conflict("not_enough_stock", "Столько свободного товара на складе нет.", {
        free: onHand,
      });
    }
    if (body.quantity < 0 && onHand + body.quantity < reservedOf(state, product.id)) {
      return conflict("below_reserved", "Остаток не может стать меньше резервов проектов.");
    }
    const cell = body.cell?.trim() ? body.cell.trim() : null;
    if (!addToCell(product, cell, body.quantity)) {
      return conflict("not_enough_stock", "В этой ячейке столько нет.");
    }
    addMovement(state, held.user, product.id, "adjustment", body.quantity, cell, body.note ?? null);
    write(state);
    return HttpResponse.json<StockProduct>(presentProduct(state, product, held.user));
  }),

  http.get("*/api/v1/erp/stock/reservations", ({ request }) => {
    const held = guard("erp.stock", "read");
    if ("error" in held) return held.error;
    const state = read();
    const number = new URL(request.url).searchParams.get("request");
    if (number && !REQUESTS.some((r) => r.number === number)) {
      return missing("calc_task_not_found", "Заявки нет среди заявок с заданием расчёта.");
    }
    const items = state.reservations
      .filter((r) => r.status === "active")
      .filter((r) => !number || r.request.slice(3) === number.slice(3))
      .map((r) => presentReservation(state, r));
    return HttpResponse.json<StockReservationList>({ items });
  }),

  http.delete("*/api/v1/erp/stock/reservations/:id", ({ params }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const state = read();
    const reservation = state.reservations.find((r) => String(r.id) === String(params["id"]));
    if (!reservation) return missing("reservation_not_found", "Резерва нет.");
    if (reservation.status !== "active") {
      return conflict("reservation_not_active", "Резерв уже снят или отгружен.");
    }
    reservation.status = reservation.shipped ? "fulfilled" : "released";
    if (reservation.shipped) reservation.quantity = reservation.shipped;
    write(state);
    return HttpResponse.json<StockReservation>(presentReservation(state, reservation));
  }),

  http.put("*/api/v1/erp/calc/:number/lines/:line/reserve", async ({ params, request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json()) as StockReserveIn;
    const state = read();
    const number = decodeURIComponent(String(params["number"]));
    const refused = reserveFor(state, held.user, number, Number(params["line"]), body.quantity);
    if (refused) return refused;
    write(state);
    return calcSheetResponse(number, held.user);
  }),

  http.delete("*/api/v1/erp/calc/:number/lines/:line/reserve", ({ params }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const state = read();
    const number = decodeURIComponent(String(params["number"]));
    const lineId = Number(params["line"]);
    const reservation = state.reservations.find(
      (r) => r.lineId === lineId && r.status === "active",
    );
    if (!reservation) return missing("reservation_not_found", "Резерва у этой строки нет.");
    reservation.status = reservation.shipped ? "fulfilled" : "released";
    write(state);
    return calcSheetResponse(number, held.user);
  }),

  http.get("*/api/v1/erp/calc/:number/price-requests", ({ params }) => {
    const held = guard("erp.calc", "read");
    if ("error" in held) return held.error;
    const number = decodeURIComponent(String(params["number"]));
    const items = read()
      .priceRequests.filter((p) => p.request === number)
      .map((p) => presentPriceRequest(p))
      .reverse();
    return HttpResponse.json<PriceRequestList>({ items });
  }),

  http.post("*/api/v1/erp/calc/:number/price-requests", async ({ params, request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json()) as PriceRequestIn;
    const number = decodeURIComponent(String(params["number"]));
    const state = read();
    const supplier = SUPPLIERS.find((s) => String(s.id) === body.supplier_id);
    if (!supplier) return missing("supplier_not_found", "Поставщика нет.");
    const email = body.to_email ?? supplier.email;
    if (!email) {
      return conflict(
        "supplier_email_required",
        "У поставщика нет почты: укажите адрес для письма.",
      );
    }
    const lines = body.line_ids.map((id) => ({
      id: Number(id),
      line: lookupCalcLine(number, Number(id)),
    }));
    if (lines.some((l) => l.line === null)) return missing("line_not_found", "Строки нет.");
    state.nextId += 1;
    const entry = {
      id: state.nextId,
      supplierId: supplier.id,
      request: number,
      requestedAt: new Date().toISOString(),
      requestedBy: held.user.name,
      toEmail: email,
      subject: `Запрос цены и срока поставки — ${number}`,
      note: body.note ?? null,
      status: "sent" as const,
      answeredAt: null,
      answeredBy: null,
      answerNote: null,
      lines: lines.map(({ id, line }) => ({
        lineId: id,
        name: line?.name ?? "",
        article: line?.article ?? "",
        quantity: line?.quantity ?? 1,
        unit: line?.unit ?? "",
      })),
    };
    state.priceRequests.push(entry);
    write(state);
    return HttpResponse.json<PriceRequest>(presentPriceRequest(entry));
  }),

  http.post("*/api/v1/erp/price-requests/:id/answer", async ({ params, request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json().catch(() => ({}))) as PriceRequestAnswerIn;
    const state = read();
    const entry = state.priceRequests.find((p) => String(p.id) === String(params["id"]));
    if (!entry) return missing("request_not_found", "Запроса нет.");
    if (entry.answeredAt) return conflict("already_answered", "Ответ поставщика уже отмечен.");
    entry.answeredAt = new Date().toISOString();
    entry.answeredBy = held.user.name;
    entry.answerNote = body.note ?? null;
    write(state);
    return HttpResponse.json<PriceRequest>(presentPriceRequest(entry));
  }),

  http.get("*/api/v1/erp/stock/suppliers", ({ request }) => {
    const held = guard("erp.stock", "read");
    if ("error" in held) return held.error;
    const q = (new URL(request.url).searchParams.get("q") ?? "").toLowerCase();
    return HttpResponse.json<StockSupplierList>({
      items: SUPPLIERS.filter((s) => `${s.name} ${s.inn}`.toLowerCase().includes(q)).map((s) => ({
        id: String(s.id),
        name: s.name,
        inn: s.inn,
        email: s.email,
      })),
    });
  }),

  http.get("*/api/v1/erp/stock/orders", ({ request }) => {
    const held = guard("erp.stock", "read");
    if ("error" in held) return held.error;
    const state = read();
    const params = new URL(request.url).searchParams;
    const status = params.get("status");
    const q = (params.get("q") ?? "").toLowerCase();
    const supplierId = params.get("supplier_id");
    const items = state.orders
      .filter((o) => !status || o.status === status)
      .filter((o) => params.get("overdue") !== "true" || overdueDays(o) !== null)
      .filter((o) => !supplierId || String(o.supplierId) === supplierId)
      .filter(
        (o) =>
          !q ||
          o.number.toLowerCase().includes(q) ||
          o.lines.some((l) => l.name.toLowerCase().includes(q)),
      )
      .map((o) => orderRow(o, held.user))
      .reverse();
    return HttpResponse.json<SupplierOrderList>({
      items,
      rights: { ...rights(held.user), prices: pricesVisible(held.user) },
    });
  }),

  http.get("*/api/v1/erp/stock/overdue", () => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const state = read();
    return HttpResponse.json<SupplierOrderList>({
      items: state.orders.filter((o) => overdueDays(o) !== null).map((o) => orderRow(o, held.user)),
      rights: { ...rights(held.user), prices: pricesVisible(held.user) },
    });
  }),

  http.post("*/api/v1/erp/stock/orders/from-request", async ({ request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json()) as SupplierOrderFromRequest;
    const state = read();
    const supplier = SUPPLIERS.find((s) => String(s.id) === body.supplier_id);
    if (!supplier) return missing("supplier_not_found", "Поставщика нет.");
    const lines = shortageLines(state, body.request);
    if (lines === null)
      return missing("calc_task_not_found", "Заявки нет среди заявок с заданием расчёта.");
    if (lines.length === 0)
      return conflict("no_shortage", "Дефицита нет: всё удержано резервом или уже заказано.");
    const order = createOrder(
      state,
      held.user,
      supplier.id,
      null,
      `Дефицит проекта ${body.request}`,
      "UZS",
      lines,
    );
    write(state);
    return HttpResponse.json<SupplierOrderDetail>(presentOrder(state, order, held.user), {
      status: 201,
    });
  }),

  http.post("*/api/v1/erp/stock/orders", async ({ request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json()) as SupplierOrderCreate;
    const state = read();
    const supplier = SUPPLIERS.find((s) => String(s.id) === body.supplier_id);
    if (!supplier) return missing("supplier_not_found", "Поставщика нет.");
    const lines = linesFrom(state, body.lines, held.user);
    if ("error" in lines) return lines.error;
    const order = createOrder(
      state,
      held.user,
      supplier.id,
      body.expected_date ?? null,
      body.note ?? "",
      body.currency ?? "UZS",
      lines.lines,
    );
    write(state);
    return HttpResponse.json<SupplierOrderDetail>(presentOrder(state, order, held.user), {
      status: 201,
    });
  }),

  http.get("*/api/v1/erp/stock/orders/:number", ({ params }) => {
    const held = guard("erp.stock", "read");
    if ("error" in held) return held.error;
    const state = read();
    const order = findOrder(state, String(params["number"]));
    return order
      ? HttpResponse.json<SupplierOrderDetail>(presentOrder(state, order, held.user))
      : orderMissing();
  }),

  http.patch("*/api/v1/erp/stock/orders/:number", async ({ params, request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json()) as SupplierOrderPatch;
    const state = read();
    const order = findOrder(state, String(params["number"]));
    if (!order) return orderMissing();
    if (order.status === "received" || order.status === "cancelled") {
      return conflict("order_closed", "Заказ закрыт: изменить его нельзя.");
    }
    if ((body.lines !== undefined || body.supplier_id !== undefined) && order.status !== "draft") {
      return conflict("order_not_draft", "Состав и поставщика можно менять только в черновике.");
    }
    if (body.supplier_id !== undefined) order.supplierId = Number(body.supplier_id);
    if ("expected_date" in body) order.expectedDate = body.expected_date ?? null;
    if (body.note !== undefined) order.note = body.note;
    if (body.lines) {
      const lines = linesFrom(state, body.lines, held.user, order);
      if ("error" in lines) return lines.error;
      order.lines = lines.lines;
    }
    log(order, held.user, "edited");
    write(state);
    return HttpResponse.json<SupplierOrderDetail>(presentOrder(state, order, held.user));
  }),

  http.post("*/api/v1/erp/stock/orders/:number/send", async ({ params, request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json().catch(() => ({}))) as SupplierOrderSendIn;
    const state = read();
    const order = findOrder(state, String(params["number"]));
    if (!order) return orderMissing();
    if (order.status !== "draft") return transitionError(order);
    const supplier = SUPPLIERS.find((s) => s.id === order.supplierId);
    const email = body.to_email ?? supplier?.email ?? null;
    if (!email)
      return conflict(
        "supplier_email_required",
        "У поставщика нет почты: укажите адрес для письма.",
      );
    order.status = "sent";
    order.sentAt = new Date().toISOString();
    order.sentTo = email;
    log(order, held.user, "sent", email);
    write(state);
    return HttpResponse.json<SupplierOrderDetail>(presentOrder(state, order, held.user));
  }),

  http.post("*/api/v1/erp/stock/orders/:number/confirm", async ({ params, request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json().catch(() => ({}))) as SupplierOrderConfirmIn;
    const state = read();
    const order = findOrder(state, String(params["number"]));
    if (!order) return orderMissing();
    if (order.status !== "sent") return transitionError(order);
    const date = body.expected_date ?? order.expectedDate;
    if (!date) return conflict("expected_date_required", "Укажите ожидаемую дату поставки.");
    order.status = "confirmed";
    order.expectedDate = date;
    order.confirmedAt = new Date().toISOString();
    log(order, held.user, "confirmed", date);
    write(state);
    return HttpResponse.json<SupplierOrderDetail>(presentOrder(state, order, held.user));
  }),

  http.post("*/api/v1/erp/stock/orders/:number/cancel", async ({ params, request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json().catch(() => ({}))) as SupplierOrderCancelIn;
    const state = read();
    const order = findOrder(state, String(params["number"]));
    if (!order) return orderMissing();
    if (order.status === "received" || order.status === "cancelled") return transitionError(order);
    if (order.lines.some((l) => l.received > 0)) {
      return conflict("order_has_receipts", "По заказу уже есть приёмка: отменить его нельзя.");
    }
    order.status = "cancelled";
    order.cancelledAt = new Date().toISOString();
    order.cancelReason = body.reason ?? null;
    log(order, held.user, "cancelled", body.reason ?? null);
    write(state);
    return HttpResponse.json<SupplierOrderDetail>(presentOrder(state, order, held.user));
  }),

  http.post("*/api/v1/erp/stock/orders/:number/receipts", async ({ params, request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json()) as SupplierOrderReceiptIn;
    const state = read();
    const order = findOrder(state, String(params["number"]));
    if (!order) return orderMissing();
    if (order.status !== "confirmed") {
      return conflict("order_not_confirmed", "Принять товар можно по подтверждённому заказу.");
    }
    for (const item of body.lines) {
      const line = order.lines.find((l) => String(l.id) === item.order_line_id);
      if (!line) return missing("line_not_found", "Строки нет в этом заказе.");
      if (item.quantity > line.quantity - line.received) {
        return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", {
          source: "erp",
          reason: "quantity_out_of_range",
          fields: ["quantity"],
          max: line.quantity - line.received,
        });
      }
    }
    state.nextId += 1;
    const receipt = {
      id: state.nextId,
      orderNumber: order.number,
      receivedAt: new Date().toISOString(),
      receivedBy: held.user.name,
      supplierDoc: body.supplier_doc ?? null,
      note: body.note ?? null,
      lines: [] as { orderLineId: number; name: string; quantity: number; cell: string | null }[],
    };
    let total = 0;
    for (const item of body.lines) {
      const line = order.lines.find((l) => String(l.id) === item.order_line_id);
      if (!line) continue;
      const cell = item.cell?.trim() ? item.cell.trim() : null;
      let product = state.products.find((p) => p.id === line.productId);
      if (!product) {
        product = {
          id: line.productId,
          name: line.name,
          article: line.article,
          unit: line.unit,
          cells: [],
        };
        state.products.push(product);
      }
      addToCell(product, cell, item.quantity);
      addMovement(state, held.user, product.id, "receipt", item.quantity, cell, order.number);
      line.received += item.quantity;
      receipt.lines.push({ orderLineId: line.id, name: line.name, quantity: item.quantity, cell });
      total += item.quantity;
      if (line.request !== null && line.lineId !== null) {
        const held_ = state.reservations.find(
          (r) => r.lineId === line.lineId && r.status === "active",
        );
        const wanted = lookupCalcLine(line.request, line.lineId)?.quantity ?? item.quantity;
        const have = held_ ? held_.quantity : 0;
        const add = Math.min(item.quantity, Math.max(wanted - have, 0));
        if (add > 0 && held_) held_.quantity += add;
        if (add > 0 && !held_) {
          state.nextId += 1;
          state.reservations.push({
            id: state.nextId,
            productId: product.id,
            request: line.request,
            lineId: line.lineId,
            quantity: add,
            shipped: 0,
            status: "active",
            createdAt: new Date().toISOString(),
            createdBy: held.user.name,
          });
        }
      }
    }
    state.receipts.push(receipt);
    log(
      order,
      held.user,
      "receipt",
      `${String(total)} шт.${body.supplier_doc ? ` · накладная ${body.supplier_doc}` : ""}`,
    );
    if (order.lines.every((l) => l.received >= l.quantity)) {
      order.status = "received";
      order.receivedAt = new Date().toISOString();
      log(order, held.user, "received");
    }
    write(state);
    return HttpResponse.json<SupplierOrderDetail>(presentOrder(state, order, held.user));
  }),

  http.get("*/api/v1/erp/stock/receipts", () => {
    const held = guard("erp.stock", "read");
    if ("error" in held) return held.error;
    const state = read();
    const pending = state.orders
      .filter((o) => o.status === "confirmed")
      .flatMap((o) =>
        o.lines
          .filter((l) => l.received < l.quantity)
          .map((l) => ({
            order_number: o.number,
            order_path: `/erp/stock/${seg(o.number)}`,
            supplier: SUPPLIERS.find((s) => s.id === o.supplierId)?.name ?? "—",
            expected_date: o.expectedDate,
            overdue: overdueDays(o) !== null,
            order_line_id: String(l.id),
            name: l.name,
            article: l.article,
            unit: l.unit,
            quantity: l.quantity,
            received_quantity: l.received,
            request: l.request ? refOf(l.request) : null,
          })),
      );
    const done = [...state.receipts].reverse().map((r) => {
      const order = state.orders.find((o) => o.number === r.orderNumber);
      return {
        id: String(r.id),
        order_number: r.orderNumber,
        order_path: `/erp/stock/${seg(r.orderNumber)}`,
        supplier: SUPPLIERS.find((s) => s.id === order?.supplierId)?.name ?? "—",
        received_at: r.receivedAt,
        received_by: r.receivedBy,
        supplier_doc: r.supplierDoc,
        quantity: r.lines.reduce((sum, l) => sum + l.quantity, 0),
        lines: r.lines.map((l) => ({ name: l.name, quantity: l.quantity, cell: l.cell })),
      };
    });
    return HttpResponse.json<StockReceipts>({ pending, done, rights: rights(held.user) });
  }),

  http.get("*/api/v1/erp/stock/shipments", ({ request }) => {
    const held = guard("erp.stock", "read");
    if ("error" in held) return held.error;
    const number = new URL(request.url).searchParams.get("request");
    const items = read()
      .shipments.filter((s) => !number || s.request.slice(3) === number.slice(3))
      .map((s) => presentShipment(s))
      .reverse();
    return HttpResponse.json<StockShipmentList>({ items, rights: rights(held.user) });
  }),

  http.post("*/api/v1/erp/stock/shipments", async ({ request }) => {
    const held = guard("erp.stock", "full");
    if ("error" in held) return held.error;
    const body = (await request.json()) as StockShipIn;
    const state = read();
    if (!body.request.startsWith("ПР")) {
      return conflict(
        "fulfillment_not_ready",
        "Проект ещё не подписан: отгрузка возможна после подписания договора.",
      );
    }
    const picked: { reservation: MockReservation; product: MockProduct; quantity: number }[] = [];
    for (const item of body.lines) {
      const reservation = state.reservations.find((r) => String(r.id) === item.reservation_id);
      if (!reservation || reservation.request !== body.request) {
        return missing("reservation_not_found", "Резерва этой заявки нет.");
      }
      if (reservation.status !== "active") {
        return conflict("reservation_not_active", "Резерв уже снят или отгружен.");
      }
      if (item.quantity > remaining(reservation)) {
        return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", {
          source: "erp",
          reason: "quantity_out_of_range",
          fields: ["quantity"],
          max: remaining(reservation),
        });
      }
      const product = state.products.find((p) => p.id === reservation.productId);
      if (!product) return missing("product_not_found", "Товара нет.");
      picked.push({ reservation, product, quantity: item.quantity });
    }
    state.shipSeq += 1;
    state.nextId += 1;
    const shipment = {
      id: state.nextId,
      number: `ОТГ-${String(new Date().getFullYear())}-${String(state.shipSeq).padStart(3, "0")}`,
      request: body.request,
      tracking: body.tracking ?? null,
      carrier: body.carrier ?? null,
      note: body.note ?? null,
      shippedAt: new Date().toISOString(),
      shippedBy: held.user.name,
      lines: [] as { productId: number; name: string; quantity: number; cell: string | null }[],
    };
    for (const { reservation, product, quantity } of picked) {
      let left = quantity;
      for (const cell of [...product.cells].sort((a, b) => b.onHand - a.onHand)) {
        if (left <= 0) break;
        const part = Math.min(cell.onHand, left);
        if (part <= 0) continue;
        cell.onHand -= part;
        left -= part;
        shipment.lines.push({
          productId: product.id,
          name: product.name,
          quantity: part,
          cell: cell.cell,
        });
        addMovement(state, held.user, product.id, "shipment", -part, cell.cell, shipment.number);
      }
      reservation.shipped += quantity;
      if (reservation.shipped >= reservation.quantity) reservation.status = "fulfilled";
    }
    state.shipments.push(shipment);
    write(state);
    return HttpResponse.json<StockShipment>(presentShipment(shipment), { status: 201 });
  }),
];

// --- общие помощники обработчиков ----------------------------------------------------------------

function presentPriceRequest(p: ReturnType<typeof read>["priceRequests"][number]): PriceRequest {
  const supplier = SUPPLIERS.find((s) => s.id === p.supplierId);
  return {
    id: String(p.id),
    supplier: { id: String(p.supplierId), name: supplier?.name ?? "Поставщик" },
    request: p.request,
    requested_at: p.requestedAt,
    requested_by: p.requestedBy,
    to_email: p.toEmail,
    subject: p.subject,
    note: p.note,
    status: p.status,
    error: null,
    answered_at: p.answeredAt,
    answered_by: p.answeredBy,
    answer_note: p.answerNote,
    lines: p.lines.map((l) => ({
      line_id: String(l.lineId),
      name: l.name,
      article: l.article,
      quantity: l.quantity,
      unit: l.unit,
    })),
  };
}

function presentShipment(s: ReturnType<typeof read>["shipments"][number]): StockShipment {
  return {
    id: String(s.id),
    number: s.number,
    request: refOf(s.request),
    tracking: s.tracking,
    carrier: s.carrier,
    note: s.note,
    shipped_at: s.shippedAt,
    shipped_by: s.shippedBy,
    lines: s.lines.map((l) => ({
      product_id: String(l.productId),
      name: l.name,
      quantity: l.quantity,
      cell: l.cell,
    })),
  };
}

type NewLine = MockOrder["lines"][number];

function linesFrom(
  state: MockStock,
  input: SupplierOrderCreate["lines"],
  user: Me,
  existing?: MockOrder,
): { lines: NewLine[] } | { error: Response } {
  const prices = pricesVisible(user);
  const lines: NewLine[] = [];
  for (const item of input) {
    if (item.unit_price !== undefined && item.unit_price !== null && !prices) {
      return {
        error: failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", {
          source: "erp",
          reason: "prices_forbidden",
          fields: ["unit_price"],
        }),
      };
    }
    const product =
      state.products.find((p) => String(p.id) === item.product_id) ??
      CATALOG.find((p) => String(p.id) === item.product_id && p.kind === "goods");
    if (!product) {
      return { error: missing("product_not_found", "Товара нет в каталоге.") };
    }
    const kept = item.id ? existing?.lines.find((l) => String(l.id) === item.id) : undefined;
    if (item.id && !kept) return { error: missing("line_not_found", "Строки нет в этом заказе.") };
    state.nextId += 1;
    lines.push({
      id: kept?.id ?? state.nextId,
      productId: Number(item.product_id),
      name: item.name || product.name,
      article: item.article || product.article,
      unit: item.unit || ("unit" in product ? product.unit : "шт."),
      quantity: item.quantity,
      received: kept?.received ?? 0,
      unitPrice: item.unit_price !== undefined ? item.unit_price : (kept?.unitPrice ?? null),
      request: "request" in item ? (item.request ?? null) : (kept?.request ?? null),
      lineId:
        "line_id" in item ? (item.line_id ? Number(item.line_id) : null) : (kept?.lineId ?? null),
    });
  }
  return { lines };
}

function createOrder(
  state: MockStock,
  user: Me,
  supplierId: number,
  expectedDate: string | null,
  note: string,
  currency: string,
  lines: NewLine[],
): MockOrder {
  state.orderSeq += 1;
  state.nextId += 1;
  const now = new Date().toISOString();
  const order: MockOrder = {
    id: state.nextId,
    number: `ЗП-${String(new Date().getFullYear())}-${String(state.orderSeq).padStart(3, "0")}`,
    status: "draft",
    supplierId,
    expectedDate,
    note,
    currency,
    createdAt: now,
    createdBy: user.name,
    sentAt: null,
    sentTo: null,
    confirmedAt: null,
    receivedAt: null,
    cancelledAt: null,
    cancelReason: null,
    lines,
    log: [],
  };
  log(order, user, "created", SUPPLIERS.find((s) => s.id === supplierId)?.name ?? null);
  state.orders.push(order);
  return order;
}

function shortageLines(state: MockStock, number: string): NewLine[] | null {
  const known = REQUESTS.find((r) => r.number.slice(3) === number.slice(3));
  if (!known) return null;
  const lines: NewLine[] = [];
  for (const lineId of calcLineIds(known.number)) {
    const line = lookupCalcLine(known.number, lineId);
    if (!line || line.productId === null) continue;
    const held = state.reservations
      .filter((r) => r.lineId === lineId && r.status === "active")
      .reduce((sum, r) => sum + remaining(r), 0);
    const ordered = state.orders
      .filter((o) => o.status === "draft" || o.status === "sent" || o.status === "confirmed")
      .flatMap((o) => o.lines)
      .filter((l) => l.lineId === lineId)
      .reduce((sum, l) => sum + l.quantity - l.received, 0);
    const shortage = line.quantity - held - ordered;
    if (shortage <= 0) continue;
    state.nextId += 1;
    lines.push({
      id: state.nextId,
      productId: line.productId,
      name: line.name,
      article: line.article,
      unit: line.unit,
      quantity: shortage,
      received: 0,
      unitPrice: null,
      request: known.number,
      lineId,
    });
  }
  return lines;
}

function calcSheetResponse(number: string, user: Me) {
  const sheet = calcSheetByNumber(number, user);
  return sheet
    ? HttpResponse.json<CalcSheet>(sheet)
    : failure(404, "NOT_FOUND", "Заявки нет среди заявок с заданием расчёта.", {
        source: "erp",
        reason: "calc_task_not_found",
      });
}
