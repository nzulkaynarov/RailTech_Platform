/**
 * Демо-данные «Расчёта по заявке» (D2-1). Заявки, клиенты, поставщики и сотрудники — вымышленные. Строки хранят
 * «сырые» значения ERP (закупка, ставка бригады, цена клиенту), а мок считает себестоимость, наценку и итоги так же,
 * как ERP (`crm.services.calculation`): закупка услуги = ставка × дни, наценка = клиенту / себестоимость − 1.
 */
export type MockKind = "goods" | "service";

export interface MockLine {
  id: number;
  name: string;
  article: string;
  productId: number | null;
  kind: MockKind;
  quantity: number;
  unit: string;
  onHand: number | null;
  supplier: {
    name: string;
    leadDays: number;
    minOrderQty: number;
    validUntil: string | null;
    offerPrice: string;
  } | null;
  leadDays: number | null;
  purchase: number;
  crewRate: number | null;
  crewDays: number | null;
  client: number;
  visa: { by: string; at: string; zone: "goods" | "services" } | null;
}

export interface MockCalc {
  number: string;
  title: string;
  client: string;
  stage: "CALCULATION" | "QUOTE";
  letterNumber: string;
  letterSubject: string;
  resolution: string;
  decidedAt: string;
  decidedBy: string;
  due: string;
  minMargin: string | null;
  manager: string;
  assignees: { zone: "goods" | "services" | "payment_terms"; name: string | null }[];
  requestText: string;
  requestLines: number;
  started: boolean;
  state: "in_progress" | "returned" | "at_director" | "approved" | "rejected";
  quoteNumber: string | null;
  directorComment: string | null;
  lines: MockLine[];
}

export interface MockCatalogItem {
  id: number;
  name: string;
  article: string;
  kind: MockKind;
  onHand: number;
  supplierName: string | null;
  leadDays: number | null;
  purchase: number;
}

export const CATALOG: readonly MockCatalogItem[] = [
  {
    id: 31,
    name: "Перевод стрелочный Р65 марки 1/11",
    article: "СП-Р65-11",
    kind: "goods",
    onHand: 1,
    supplierName: "ООО «Вымышленная Сталь»",
    leadDays: 45,
    purchase: 90_000_000,
  },
  {
    id: 32,
    name: "Привод стрелочный электромеханический СП-6М",
    article: "СП-6М",
    kind: "goods",
    onHand: 6,
    supplierName: "ООО «Демо Автоматика»",
    leadDays: 30,
    purchase: 12_500_000,
  },
  {
    id: 33,
    name: "Брус переводной деревянный, комплект",
    article: "БП-1/11",
    kind: "goods",
    onHand: 0,
    supplierName: "ООО «Пример Лес»",
    leadDays: 20,
    purchase: 8_400_000,
  },
  {
    id: 34,
    name: "Монтаж и пусконаладка стрелочного перевода",
    article: "",
    kind: "service",
    onHand: 0,
    supplierName: null,
    leadDays: null,
    purchase: 0,
  },
];

export function seedCalcs(): MockCalc[] {
  return [
    {
      number: "ЗВ-2026-097",
      title: "Стрелочные переводы Р65 с монтажом",
      client: "АО «Пример Логистик»",
      stage: "CALCULATION",
      letterNumber: "ВХ-097/26",
      letterSubject: "Запрос КП на стрелочные переводы и монтаж",
      resolution:
        "Посчитать переводы со склада и под заказ, монтаж — бригадой. Срок — до пятницы, маржа не ниже 15 %.",
      decidedAt: "2026-10-27T05:30:00Z",
      decidedBy: "Демо Директоров",
      due: "2026-10-30",
      minMargin: "15.00",
      manager: "Демо Менеджеров",
      assignees: [
        { zone: "goods", name: "Демо Снабженцев" },
        { zone: "services", name: "Демо Инженеров" },
      ],
      requestText:
        "Просим посчитать 2 стрелочных перевода Р65 марки 1/11, 4 привода СП-6М и монтаж переводов бригадой на станции заказчика.",
      requestLines: 3,
      started: true,
      state: "in_progress",
      quoteNumber: null,
      directorComment: null,
      lines: [
        {
          id: 501,
          name: "Перевод стрелочный Р65 марки 1/11",
          article: "СП-Р65-11",
          productId: 31,
          kind: "goods",
          quantity: 2,
          unit: "шт.",
          onHand: 1,
          supplier: {
            name: "ООО «Вымышленная Сталь»",
            leadDays: 45,
            minOrderQty: 1,
            validUntil: "2026-12-31",
            offerPrice: "90000000.00",
          },
          leadDays: 45,
          purchase: 90_000_000,
          crewRate: null,
          crewDays: null,
          client: 103_500_000,
          visa: null,
        },
        {
          id: 502,
          name: "Привод стрелочный электромеханический СП-6М",
          article: "СП-6М",
          productId: 32,
          kind: "goods",
          quantity: 4,
          unit: "шт.",
          onHand: 6,
          supplier: {
            name: "ООО «Демо Автоматика»",
            leadDays: 30,
            minOrderQty: 2,
            validUntil: null,
            offerPrice: "12500000.00",
          },
          leadDays: 5,
          purchase: 12_500_000,
          crewRate: null,
          crewDays: null,
          client: 14_375_000,
          visa: null,
        },
        {
          id: 503,
          name: "Монтаж и пусконаладка стрелочного перевода",
          article: "",
          productId: 34,
          kind: "service",
          quantity: 2,
          unit: "компл.",
          onHand: null,
          supplier: null,
          leadDays: null,
          purchase: 4_500_000,
          crewRate: 1_500_000,
          crewDays: 3,
          client: 5_400_000,
          visa: null,
        },
      ],
    },
    {
      number: "ЗВ-2026-101",
      title: "Брус переводной для ремонта путей",
      client: "ООО «Демо-Рейл»",
      stage: "CALCULATION",
      letterNumber: "ВХ-101/26",
      letterSubject: "Запрос цены на переводной брус",
      resolution: "Посчитать брус под заказ, сроки поставщика уточнить.",
      decidedAt: "2026-10-26T08:00:00Z",
      decidedBy: "Демо Директоров",
      due: "2026-10-29",
      minMargin: null,
      manager: "Демо Менеджеров",
      assignees: [{ zone: "goods", name: "Демо Снабженцев" }],
      requestText: "Нужен переводной брус на 3 перевода марки 1/11.",
      requestLines: 1,
      started: true,
      state: "at_director",
      quoteNumber: "КП-2026/112",
      directorComment: null,
      lines: [
        {
          id: 511,
          name: "Брус переводной деревянный, комплект",
          article: "БП-1/11",
          productId: 33,
          kind: "goods",
          quantity: 3,
          unit: "компл.",
          onHand: 0,
          supplier: {
            name: "ООО «Пример Лес»",
            leadDays: 20,
            minOrderQty: 1,
            validUntil: "2026-11-30",
            offerPrice: "8400000.00",
          },
          leadDays: 20,
          purchase: 8_400_000,
          crewRate: null,
          crewDays: null,
          client: 9_660_000,
          visa: { by: "Демо Снабженцев", at: "2026-10-27T09:10:00Z", zone: "goods" },
        },
      ],
    },
    {
      number: "ЗВ-2026-103",
      title: "Обследование стрелочного хозяйства",
      client: "ГУП «Вымышленная дорога»",
      stage: "CALCULATION",
      letterNumber: "ВХ-103/26",
      letterSubject: "Обследование и ремонт стрелок",
      resolution:
        "Гл. инженеру — объём работ и бригада; снабжению — материалы по итогам обследования.",
      decidedAt: "2026-10-27T11:15:00Z",
      decidedBy: "Демо Директоров",
      due: "2026-11-03",
      minMargin: "20.00",
      manager: "Демо Менеджеров",
      assignees: [
        { zone: "services", name: "Демо Инженеров" },
        { zone: "goods", name: null },
      ],
      requestText:
        "Просим обследовать 6 стрелочных переводов на подъездном пути и предложить ремонт с заменой изношенных деталей.",
      requestLines: 0,
      started: false,
      state: "in_progress",
      quoteNumber: null,
      directorComment: null,
      lines: [],
    },
  ];
}

/** Предложение ИИ-разбора для текста заявки (детерминированно: e2e и снимки не плавают). */
export const PARSE_PROPOSAL = [
  { name: "Обследование стрелочного перевода", quantity: 6, unit: "шт.", article: "", note: "" },
  {
    name: "Крестовина стрелочная Р65 1/11",
    quantity: 2,
    unit: "шт.",
    article: "КР-Р65-11",
    note: "",
  },
  {
    name: "Остряк стрелочный Р65",
    quantity: 4,
    unit: "шт.",
    article: "",
    note: "по итогам обследования",
  },
];
