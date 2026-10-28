/**
 * Демо-данные «Склада» (D2-2): остатки по ячейкам, резервы, заказы поставщикам ЗП, приёмки, отгрузки и запросы цены.
 * Поставщики, заявки и сотрудники вымышленные (репозиторий публичный). Состояние хранит и меняет мок `erpStock.ts` так же,
 * как ERP (`inventory.services.stock`, `supply.services.orders`): свободный остаток = остаток − резервы, приёмка растит
 * остаток, отгрузка уменьшает остаток и резерв.
 */
export type OrderStatus = "draft" | "sent" | "confirmed" | "received" | "cancelled";

export interface MockProduct {
  id: number;
  name: string;
  article: string;
  unit: string;
  cells: { cell: string | null; onHand: number }[];
}

export interface MockRequest {
  number: string;
  client: string;
}

export interface MockSupplier {
  id: number;
  name: string;
  inn: string;
  email: string | null;
}

export interface MockReservation {
  id: number;
  productId: number;
  request: string;
  lineId: number | null;
  quantity: number;
  shipped: number;
  status: "active" | "released" | "fulfilled";
  createdAt: string;
  createdBy: string;
}

export interface MockOrderLine {
  id: number;
  productId: number;
  name: string;
  article: string;
  unit: string;
  quantity: number;
  received: number;
  unitPrice: string | null;
  request: string | null;
  lineId: number | null;
}

export interface MockOrderLog {
  kind:
    "created" | "edited" | "sent" | "confirmed" | "receipt" | "received" | "cancelled" | "overdue";
  at: string;
  by: string;
  detail: string | null;
}

export interface MockReceipt {
  id: number;
  orderNumber: string;
  receivedAt: string;
  receivedBy: string;
  supplierDoc: string | null;
  note: string | null;
  lines: { orderLineId: number; name: string; quantity: number; cell: string | null }[];
}

export interface MockOrder {
  id: number;
  number: string;
  status: OrderStatus;
  supplierId: number;
  expectedDate: string | null;
  note: string;
  currency: string;
  createdAt: string;
  createdBy: string;
  sentAt: string | null;
  sentTo: string | null;
  confirmedAt: string | null;
  receivedAt: string | null;
  cancelledAt: string | null;
  cancelReason: string | null;
  lines: MockOrderLine[];
  log: MockOrderLog[];
}

export interface MockShipment {
  id: number;
  number: string;
  request: string;
  tracking: string | null;
  carrier: string | null;
  note: string | null;
  shippedAt: string;
  shippedBy: string;
  lines: { productId: number; name: string; quantity: number; cell: string | null }[];
}

export interface MockPriceRequest {
  id: number;
  supplierId: number;
  request: string;
  requestedAt: string;
  requestedBy: string;
  toEmail: string;
  subject: string;
  note: string | null;
  status: "sent" | "failed";
  answeredAt: string | null;
  answeredBy: string | null;
  answerNote: string | null;
  lines: { lineId: number; name: string; article: string; quantity: number; unit: string }[];
}

export interface MockMovement {
  productId: number;
  kind: "receipt" | "shipment" | "adjustment";
  quantity: number;
  cell: string | null;
  at: string;
  by: string;
  note: string | null;
}

export interface MockStock {
  products: MockProduct[];
  reservations: MockReservation[];
  orders: MockOrder[];
  receipts: MockReceipt[];
  shipments: MockShipment[];
  priceRequests: MockPriceRequest[];
  movements: MockMovement[];
  nextId: number;
  orderSeq: number;
  shipSeq: number;
}

export const REQUESTS: readonly MockRequest[] = [
  { number: "ЗВ-2026-097", client: "АО «Пример Логистик»" },
  { number: "ПР-2026-099", client: "ООО «Демо-Депо»" },
];

export const SUPPLIERS: readonly MockSupplier[] = [
  { id: 5, name: "ООО «Вымышленная Сталь»", inn: "7700000302", email: "sales@steel.example" },
  { id: 6, name: "ООО «Пример Лес»", inn: "7700000303", email: null },
];

export const YEAR = new Date().getFullYear();
const day = (offset: number): string => {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return date.toISOString().slice(0, 10);
};

/** Исходное состояние: стрелочные приводы на складе, скрепления в резерве проекта, заказ поставщику, не пришедший в срок. */
export function seedStock(): MockStock {
  const now = new Date().toISOString();
  return {
    products: [
      {
        id: 31,
        name: "Перевод стрелочный Р65 марки 1/11",
        article: "СП-Р65-11",
        unit: "шт.",
        cells: [{ cell: "A-03-2", onHand: 1 }],
      },
      {
        id: 32,
        name: "Привод стрелочный электромеханический СП-6М",
        article: "СП-6М",
        unit: "шт.",
        cells: [
          { cell: "B-04-1", onHand: 4 },
          { cell: "B-04-2", onHand: 2 },
        ],
      },
      {
        id: 41,
        name: "Скрепление рельсовое КБ-65",
        article: "КБ-65",
        unit: "компл.",
        cells: [{ cell: "C-01-1", onHand: 50 }],
      },
    ],
    reservations: [
      {
        id: 1,
        productId: 41,
        request: "ПР-2026-099",
        lineId: 801,
        quantity: 20,
        shipped: 0,
        status: "active",
        createdAt: now,
        createdBy: "Демо Снабженцев",
      },
    ],
    orders: [
      {
        id: 29,
        number: `ЗП-${String(YEAR)}-029`,
        status: "confirmed",
        supplierId: 5,
        expectedDate: day(-3),
        note: "",
        currency: "UZS",
        createdAt: now,
        createdBy: "Демо Снабженцев",
        sentAt: now,
        sentTo: "sales@steel.example",
        confirmedAt: now,
        receivedAt: null,
        cancelledAt: null,
        cancelReason: null,
        lines: [
          {
            id: 290,
            productId: 41,
            name: "Скрепление рельсовое КБ-65",
            article: "КБ-65",
            unit: "компл.",
            quantity: 30,
            received: 0,
            unitPrice: "185000.00",
            request: null,
            lineId: null,
          },
        ],
        log: [
          { kind: "created", at: now, by: "Демо Снабженцев", detail: "ООО «Вымышленная Сталь»" },
          { kind: "sent", at: now, by: "Демо Снабженцев", detail: "sales@steel.example" },
          { kind: "confirmed", at: now, by: "Демо Снабженцев", detail: day(-3) },
        ],
      },
    ],
    receipts: [],
    shipments: [],
    priceRequests: [],
    movements: [],
    nextId: 1000,
    orderSeq: 29,
    shipSeq: 0,
  };
}
