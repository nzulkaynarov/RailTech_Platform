/**
 * Демо-данные «Расчёта по заявке» (D2-1). Заявки, клиенты, партнёры и сотрудники — вымышленные. Строки хранят
 * «сырые» значения ERP (закупка, ставка бригады, цена клиенту), а мок считает себестоимость, наценку и итоги так же,
 * как ERP (`crm.services.calculation`): закупка услуги = ставка × дни, наценка = клиенту / себестоимость − 1.
 */
export type MockKind = "goods" | "service";

export interface MockLine {
  id: number;
  name: string;
  article: string;
  productId: number | null;
  /** СЦ-10: строка без карточки похожа на позицию каталога — «Выбрать» или «Новая позиция». */
  catalogHint?: { id: number; name: string } | null;
  kind: MockKind;
  quantity: number;
  unit: string;
  /** ADR-0027 п. 10: код единицы справочника; нет — единица текстом */
  unitCode?: string;
  onHand: number | null;
  supplier: {
    name: string;
    leadDays: number;
    minOrderQty: number;
    validUntil: string | null;
    offerPrice: string;
  } | null;
  leadDays: number | null;
  /** РАСЧ-1: цены партнёров по карточке строки (мок BFF); `offerId` — по какой взята закупка (null — введена руками). */
  partner?: {
    offerId: number | null;
    options: {
      id: number;
      supplier: string;
      price: number;
      currency: string;
      priceDate: string;
      validUntil: string | null;
      freshness: "ok" | "expiring" | "stale";
    }[];
    expired?: { supplier: string; validUntil: string } | null;
  };
  purchase: number;
  /** Валюта закупки строки; нет — сумы. */
  currency?: string;
  crewRate: number | null;
  crewDays: number | null;
  client: number;
  visa: { by: string; at: string; zone: "goods" | "services" } | null;
}

export interface MockCalc {
  number: string;
  title: string;
  client: string;
  stage: "CALCULATION" | "QUOTE" | "LOST" | "DONE";
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
  /** Файлы, которые клиент приложил к заявке в кабинете (СЦ-10). */
  requestFiles?: { id: number; name: string; uploaded_at: string }[];
  started: boolean;
  state: "in_progress" | "returned" | "at_director" | "approved" | "rejected";
  quoteNumber: string | null;
  directorComment: string | null;
  /** Версия КП (как ERP `Quote.version`): повторный «Расчёт готов» после возврата и «Новая версия КП» — +1 */
  version?: number;
  /** Кто отклонил КП при `state = rejected` (D26G-3) и почему */
  rejectedBy?: "client" | "director" | null;
  rejectReason?: string | null;
  /** «Закрыть заявку» (ЛХ-2): код причины и комментарий */
  closeReason?: string;
  closeComment?: string;
  /** Условия КП (план 0.5): нет — умолчания компании мока */
  terms?: {
    payment_terms: string | null;
    valid_until: string | null;
    delivery_days: number | null;
    delivery_note: string | null;
  };
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

/**
 * РАСЧ-1: заявка с реалистичным расчётом для приёмки — 12 строк, длинные названия, два партнёра в разных валютах,
 * одна истёкшая цена, одна строка без цены, строки с маржой ниже порога. Вымышленные названия.
 */
function wideCalc(base: MockCalc): MockCalc {
  const alpha = "ООО «Вымышленная Сталь»";
  const beta = "ООО «Демо Металл»";
  const items: [string, string, number, number, number, number | null][] = [
    // название, артикул, кол-во, закупка (сум), цена клиенту (сум), срок
    [
      "Насос центробежный консольный горизонтальный, нержавеющая сталь, фланцы DN80, 15 кВт",
      "НЦК-80-15",
      2,
      31_500_000,
      38_000_000,
      21,
    ],
    [
      "Кабель силовой медный с изоляцией из сшитого полиэтилена 3×95+1×50, барабан 500 м",
      "КС-3095",
      3,
      48_200_000,
      56_900_000,
      14,
    ],
    [
      "Шкаф управления электроприводом со степенью защиты IP65 и частотным преобразователем",
      "ШУ-65",
      1,
      27_800_000,
      28_400_000,
      30,
    ],
    ["Задвижка клиновая стальная фланцевая DN100 PN16", "ЗК-100", 8, 2_950_000, 3_540_000, 10],
    [
      "Датчик давления измерительный 0–1,6 МПа, выход 4–20 мА",
      "ДД-16",
      12,
      1_180_000,
      1_330_000,
      7,
    ],
    ["Фильтр сетчатый осадочный фланцевый DN100", "ФС-100", 6, 1_640_000, 1_960_000, 12],
    [
      "Редуктор цилиндрический двухступенчатый, передаточное число 25",
      "РЦ-25",
      2,
      19_300_000,
      21_700_000,
      25,
    ],
    [
      "Подшипниковый узел в сборе для насосных агрегатов серии НЦК",
      "ПУ-НЦК",
      10,
      860_000,
      1_040_000,
      5,
    ],
    [
      "Комплект уплотнений торцевых для насосов НЦК-80, двойное исполнение",
      "КУ-80",
      4,
      3_120_000,
      3_760_000,
      9,
    ],
    [
      "Автоматический выключатель в литом корпусе 250 А, 3 полюса",
      "АВ-250",
      5,
      2_240_000,
      2_890_000,
      6,
    ],
    [
      "Преобразователь частоты 15 кВт, 380 В, со встроенным фильтром ЭМС",
      "ПЧ-15",
      2,
      14_600_000,
      15_100_000,
      18,
    ],
    ["Манометр показывающий с глицериновым заполнением, класс 1,0", "МП-10", 20, 310_000, 0, null],
  ];
  const partner = (i: number): MockLine["partner"] => {
    if (i === 11) return { offerId: null, options: [], expired: null };
    if (i === 8) {
      return {
        offerId: null,
        options: [],
        expired: { supplier: beta, validUntil: "2026-11-10" },
      };
    }
    const price = items[i]?.[3] ?? 0;
    const usd = i % 3 === 1;
    const opts: NonNullable<MockLine["partner"]>["options"] = [
      {
        id: 100 + i * 2,
        supplier: usd ? beta : alpha,
        price: usd ? Math.round(price / 12_000) : price,
        currency: usd ? "USD" : "UZS",
        priceDate: "2026-11-24",
        validUntil: i === 4 ? "2026-12-02" : "2026-12-31",
        freshness: i === 4 ? "expiring" : "ok",
      },
      {
        id: 101 + i * 2,
        supplier: usd ? alpha : beta,
        price: usd ? Math.round(price * 1.04) : Math.round(price / 12_000) + 40,
        currency: usd ? "UZS" : "USD",
        priceDate: "2026-11-18",
        validUntil: "2026-12-20",
        freshness: "ok" as const,
      },
    ];
    return { offerId: opts[0]?.id ?? null, options: opts };
  };
  const lines: MockLine[] = items.map(([name, article, quantity, purchase, client, lead], i) => ({
    id: 900 + i,
    name,
    article,
    productId: 70 + i,
    kind: "goods",
    quantity,
    unit: "шт.",
    onHand: i % 4 === 0 ? 1 : 0,
    supplier: (() => {
      const chosen = partner(i)?.options[0];
      return chosen
        ? {
            name: chosen.supplier,
            leadDays: lead ?? 0,
            minOrderQty: 1,
            validUntil: chosen.validUntil,
            offerPrice: `${String(chosen.price)}.00`,
          }
        : null;
    })(),
    leadDays: lead,
    partner: partner(i),
    purchase: i === 11 || i === 8 ? 0 : purchase,
    currency: "UZS",
    crewRate: null,
    crewDays: null,
    client: i === 11 || i === 8 ? 0 : client,
    visa: null,
  }));
  return {
    ...base,
    number: "ЗВ-2026-121",
    title: "Заявка ЗВ-2026-121 · насосное и электрооборудование",
    letterNumber: "ВХ-121/26",
    letterSubject: "Запрос КП на насосное и электрооборудование для цеха",
    requestLines: lines.length,
    requestFiles: [],
    assignees: [{ zone: "goods", name: "Демо Снабженцев" }],
    lines,
  };
}

export function seedCalcs(): MockCalc[] {
  const seeds = baseCalcs();
  const first = seeds.find((c) => c.number === "ЗВ-2026-097");
  return first ? [...seeds, wideCalc(first)] : seeds;
}

function baseCalcs(): MockCalc[] {
  return [
    // ЗАЯВ-1: прошлые заявки реестра — закрытая с причиной, КП ушло клиенту, стала проектом
    {
      number: "ЗВ-2026-081",
      title: "Щебень фракции 20–40",
      client: "ООО «Демо-Депо»",
      stage: "LOST",
      letterNumber: "ВХ-081/26",
      letterSubject: "Запрос цены на щебень",
      resolution: "Посчитать, срок — три дня.",
      decidedAt: "2026-10-12T06:00:00Z",
      decidedBy: "Демо Директоров",
      due: "2026-10-15",
      minMargin: "15.00",
      manager: "Демо Широков",
      assignees: [{ zone: "goods", name: "Демо Широков" }],
      requestText: "Нужно 40 т щебня фракции 20–40, доставка на станцию.",
      requestLines: 1,
      requestFiles: [{ id: 21, name: "zapros-shebyon.pdf", uploaded_at: "2026-10-12T05:40:00Z" }],
      started: true,
      state: "in_progress",
      quoteNumber: null,
      directorComment: null,
      closeReason: "NO_REPLY",
      closeComment: "",
      lines: [],
    },
    {
      number: "ЗВ-2026-084",
      title: "Крепёж для стрелочных переводов",
      client: "АО «Пример Логистик»",
      stage: "QUOTE",
      letterNumber: "ВХ-084/26",
      letterSubject: "Запрос КП на крепёж",
      resolution: "Посчитать со склада.",
      decidedAt: "2026-10-14T06:00:00Z",
      decidedBy: "Демо Директоров",
      due: "2026-10-17",
      minMargin: "15.00",
      manager: "Демо Широков",
      assignees: [{ zone: "goods", name: "Демо Широков" }],
      requestText: "Нужны 200 комплектов накладок и болтов.",
      requestLines: 2,
      requestFiles: [{ id: 22, name: "kreplenie.xlsx", uploaded_at: "2026-10-14T05:40:00Z" }],
      started: true,
      state: "approved",
      quoteNumber: "КП-2026/090",
      directorComment: null,
      version: 1,
      lines: [],
    },
    {
      number: "ЗВ-2026-079",
      title: "Монтаж стрелочного перевода",
      client: "ООО «Демо-Депо»",
      stage: "DONE",
      letterNumber: "ВХ-079/26",
      letterSubject: "Запрос КП на монтаж",
      resolution: "Посчитать бригаду.",
      decidedAt: "2026-10-05T06:00:00Z",
      decidedBy: "Демо Директоров",
      due: "2026-10-08",
      minMargin: "15.00",
      manager: "Демо Широков",
      assignees: [{ zone: "services", name: "Демо Инженеров" }],
      requestText: "Монтаж одного стрелочного перевода на станции.",
      requestLines: 1,
      started: true,
      state: "approved",
      quoteNumber: "КП-2026/081",
      directorComment: null,
      version: 1,
      lines: [],
    },
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
      requestFiles: [{ id: 7, name: "spec.pdf", uploaded_at: "2026-10-27T05:40:00Z" }],
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
          partner: {
            offerId: 11,
            options: [
              {
                id: 11,
                supplier: "ООО «Вымышленная Сталь»",
                price: 90_000_000,
                currency: "UZS",
                priceDate: "2026-11-20",
                validUntil: "2026-12-31",
                freshness: "ok",
              },
              {
                id: 12,
                supplier: "ООО «Демо Металл»",
                price: 7_900,
                currency: "USD",
                priceDate: "2026-11-24",
                validUntil: "2026-12-15",
                freshness: "ok",
              },
            ],
          },
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
      resolution: "Посчитать брус под заказ, сроки партнёра уточнить.",
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
      // Товары — менеджеру-универсалу (пилот, W-1): его «Мои задачи» начинаются с «Начать расчёт» (D2-8)
      assignees: [
        { zone: "services", name: "Демо Инженеров" },
        { zone: "goods", name: "Демо Широков" },
      ],
      requestText:
        "Просим обследовать 6 стрелочных переводов на подъездном пути и предложить ремонт с заменой изношенных деталей.",
      requestLines: 0,
      requestFiles: [
        { id: 8, name: "Ведомость брусьев.xlsx", uploaded_at: "2026-10-28T07:10:00Z" },
      ],
      started: false,
      state: "in_progress",
      quoteNumber: null,
      directorComment: null,
      lines: [],
    },
    {
      // D26G-3: клиент отклонил КП в кабинете — заявка вернулась в расчёт, решение за менеджером
      number: "ЗВ-2026-109",
      title: "Приводы стрелочные для станции",
      client: "ООО «Демо-Депо»",
      stage: "CALCULATION",
      letterNumber: "ВХ-109/26",
      letterSubject: "Запрос КП на стрелочные приводы",
      resolution: "Посчитать приводы со склада, маржа не ниже 15 %.",
      decidedAt: "2026-10-24T06:00:00Z",
      decidedBy: "Демо Директоров",
      due: "2026-10-28",
      minMargin: "15.00",
      manager: "Демо Широков",
      assignees: [{ zone: "goods", name: "Демо Широков" }],
      requestText: "Нужны 4 привода СП-6М со склада.",
      requestLines: 1,
      started: true,
      state: "rejected",
      quoteNumber: "КП-2026/119",
      directorComment: null,
      version: 1,
      rejectedBy: "client",
      rejectReason: "Дорого: у конкурента на 7 % ниже, просим пересмотреть цену привода",
      lines: [
        {
          id: 591,
          name: "Привод стрелочный электромеханический СП-6М",
          article: "СП-6М",
          productId: 32,
          kind: "goods",
          quantity: 4,
          unit: "шт.",
          onHand: 6,
          supplier: null,
          leadDays: 5,
          purchase: 12_500_000,
          crewRate: null,
          crewDays: null,
          client: 15_000_000,
          visa: { by: "Демо Широков", at: "2026-10-26T09:00:00Z", zone: "goods" },
        },
      ],
    },
  ];
}

/** Предложение ИИ-разбора для текста заявки (детерминированно: e2e и снимки не плавают). */
export const PARSE_PROPOSAL = [
  {
    name: "Обследование стрелочного перевода",
    quantity: 6,
    unit: "шт.",
    unit_code: "H87",
    article: "",
    note: "",
  },
  {
    name: "Крестовина стрелочная Р65 1/11",
    quantity: 2,
    unit: "шт.",
    unit_code: "H87",
    article: "КР-Р65-11",
    note: "",
  },
  {
    name: "Остряк стрелочный Р65",
    quantity: 4,
    unit: "шт.",
    unit_code: "H87",
    article: "",
    note: "по итогам обследования",
  },
];
