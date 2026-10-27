import type {
  EdsPerson,
  EdsRouteStep,
  MemoApprovalCard,
  QuoteApprovalCard,
  QuoteChecklistLine,
} from "../../shared/api/generated/model";

/**
 * Вымышленные КП на одобрение и документы на согласовании для MSW (D1-4, BFF 0.22.0): те же формы, что вернёт BFF по
 * `platform-bff.yaml`. Названия компаний и имена выдуманы (репозиторий публичный). Состояние живёт в памяти страницы: решение
 * меняет маршрут, и следующий запрос списка и карточки его видит; `resetApprovals()` возвращает исходное (тесты).
 */
const person = (id: number, name: string): EdsPerson => ({ crm_user_id: id, full_name: name });
export const SUPPLY_PERSON = person(31, "Демо Снабженцев");
export const ENGINEER_PERSON = person(41, "Демо Инженеров");
export const MANAGER_PERSON = person(2, "Демо Менеджеров");
export const DIRECTOR_PERSON = person(1, "Демо Директоров");
export const OFFICE_PERSON = person(61, "Демо Офисовая");
export const ACCOUNTANT_PERSON = person(51, "Демо Бухгалтеров");
/** Сотрудник сессии мока -> `crm_user_id` автора (менеджер мока пишет служебки от своего имени). */
export const MOCK_USER_CRM_ID: Record<string, number> = {
  "u-demo-manager": 2,
  "u-demo-director": 1,
  "u-demo-supply": 31,
  "u-demo-accountant": 51,
};

const step = (
  label: string,
  status: EdsRouteStep["status"],
  extra: Partial<EdsRouteStep> = {},
): EdsRouteStep => ({
  label,
  status,
  decided_by: null,
  decided_at: null,
  comment: null,
  ...extra,
});

function line(
  code: QuoteChecklistLine["code"],
  ok: boolean,
  extra: Partial<QuoteChecklistLine> = {},
): QuoteChecklistLine {
  return {
    code,
    ok,
    blocking: code !== "due",
    by_name: null,
    at: null,
    ...extra,
  };
}

interface QuoteSeed {
  n: number;
  version?: number;
  client: string;
  request: number;
  title: string;
  total: string;
  subtotal: string;
  vat: string;
  cost: string;
  marginPct: string;
  marginAmount: string;
  /** Красные строки чек-листа */
  red?: ("visa_services" | "due")[];
  /** ERP не ответил: строк и итогов нет, остаётся снимок EDS */
  erpDown?: boolean;
  channels: { telegram: boolean; cabinet: boolean; email: boolean };
  lines: [string, number, string, string, number][];
}

const QUOTE_SEEDS: readonly QuoteSeed[] = [
  {
    n: 115,
    version: 2,
    client: "ООО «Демо-Рейл»",
    request: 104,
    title: "Стрелочные приводы",
    total: "125000000.00",
    subtotal: "111607142.86",
    vat: "13392857.14",
    cost: "103000000.00",
    marginPct: "17.6",
    marginAmount: "22000000.00",
    channels: { telegram: true, cabinet: true, email: true },
    lines: [
      ["Привод стрелочный СП-6", 12, "шт", "8500000.00", 45],
      ["Шефмонтаж и наладка", 1, "усл", "9607142.86", 10],
    ],
  },
  {
    n: 116,
    client: "АО «Демо-Транс»",
    request: 105,
    title: "Рельсовые скрепления",
    total: "56000000.00",
    subtotal: "50000000.00",
    vat: "6000000.00",
    cost: "44000000.00",
    marginPct: "12.0",
    marginAmount: "6000000.00",
    red: ["visa_services"],
    channels: { telegram: true, cabinet: false, email: true },
    lines: [["Скрепление рельсовое ЖБР-65", 4000, "компл", "12500.00", 30]],
  },
  {
    n: 117,
    client: "ООО «Демо-Сигнал»",
    request: 106,
    title: "Автоблокировка",
    total: "89600000.00",
    subtotal: "80000000.00",
    vat: "9600000.00",
    cost: "68000000.00",
    marginPct: "15.0",
    marginAmount: "12000000.00",
    red: ["due"],
    channels: { telegram: true, cabinet: true, email: false },
    lines: [
      ["Светофор постоянного света", 8, "шт", "6000000.00", 60],
      ["Монтаж устройств автоблокировки", 1, "усл", "32000000.00", 20],
    ],
  },
  {
    n: 118,
    client: "ООО «Демо-Кабель»",
    request: 107,
    title: "Кабель СБ",
    total: "42000000.00",
    subtotal: "37500000.00",
    vat: "4500000.00",
    cost: "33000000.00",
    marginPct: "21.4",
    marginAmount: "9000000.00",
    erpDown: true,
    channels: { telegram: true, cabinet: true, email: true },
    lines: [["Кабель сигнально-блокировочный", 6000, "м", "6250.00", 25]],
  },
];

function quote(seed: QuoteSeed): QuoteApprovalCard {
  const version = seed.version ?? 1;
  const number = `КП-2026/${String(seed.n)}`;
  const requestNumber = `ЗВ-2026-${String(seed.request)}`;
  const red = seed.red ?? [];
  const checklist: QuoteChecklistLine[] = [
    line("visa_goods", true, { by_name: SUPPLY_PERSON.full_name, at: "2026-10-28T07:40:00Z" }),
    red.includes("visa_services")
      ? line("visa_services", false)
      : line("visa_services", true, {
          by_name: ENGINEER_PERSON.full_name,
          at: "2026-10-28T08:10:00Z",
        }),
    line("margin", true, {
      at: "2026-10-28T08:55:00Z",
      value: `${seed.marginPct} % ≥ 15 %`.replace("12.0 % ≥", "12.0 % ≥"),
    }),
    line("due", !red.includes("due"), { value: "2026-10-28" }),
  ];
  if (red.includes("visa_services")) {
    // Маржа ниже порога у КП без визы — вторая красная строка (визы и маржа блокируют)
    checklist[2] = line("margin", false, { at: "2026-10-28T08:55:00Z", value: "12.0 % < 15 %" });
  }
  const blocked = checklist.some((c) => c.blocking && !c.ok);
  return {
    id: `40000000-0000-4000-8000-${String(seed.n).padStart(12, "0")}`,
    number,
    version,
    round: version,
    status: "open",
    stage: "QUOTE",
    can_decide: true,
    allowed_decisions: blocked ? ["return", "reject"] : ["approve", "return", "reject"],
    approved_late: false,
    outgoing_number: null,
    created_at: "2026-10-28T08:56:00Z",
    ready_at: "2026-10-28T08:55:00Z",
    due: "2026-10-28",
    client_name: seed.client,
    request: {
      number: requestNumber,
      title: seed.title,
      path: `/crm/requests?request=${encodeURIComponent(requestNumber)}&panel=open&tab=card`,
    },
    letter: {
      number: `ВХ-${String(seed.request)}/26`,
      path: `/eds/inbox/${encodeURIComponent(`ВХ-${String(seed.request)}/26`)}`,
    },
    calculated_by: [
      { name: SUPPLY_PERSON.full_name, zone: "goods" },
      ...(red.includes("visa_services")
        ? []
        : [{ name: ENGINEER_PERSON.full_name, zone: "services" as const }]),
    ],
    snapshot_total: { amount: seed.total, currency: "UZS" },
    totals_mismatch: false,
    lines: seed.erpDown
      ? null
      : seed.lines.map(([name, quantity, unit, price, lead], index) => ({
          position: index + 1,
          name,
          quantity,
          unit,
          unit_price: price,
          amount: (Math.round(Number(price) * quantity * 100) / 100).toFixed(2),
          lead_time_days: lead,
          optional: false,
        })),
    totals: seed.erpDown
      ? null
      : {
          currency: "UZS",
          subtotal: seed.subtotal,
          vat_rate: "12",
          vat_amount: seed.vat,
          total: seed.total,
        },
    internal: {
      cost: seed.cost,
      margin_amount: seed.marginAmount,
      margin_pct: seed.marginPct,
      min_margin_pct: "15",
      payment_terms: null,
      valid_until: "2026-11-27",
      supplier_price_until: null,
    },
    checklist,
    steps: [step("Директор", "current")],
    channels: { contact_name: "Алия Демо", ...seed.channels },
    sources: { crm: "ok", erp: seed.erpDown ? "unavailable" : "ok" },
  };
}

function approvedQuote(): QuoteApprovalCard {
  const base = quote({
    n: 113,
    client: "ООО «Демо-Путь»",
    request: 101,
    title: "Щебень",
    total: "33600000.00",
    subtotal: "30000000.00",
    vat: "3600000.00",
    cost: "25500000.00",
    marginPct: "15.0",
    marginAmount: "4500000.00",
    channels: { telegram: true, cabinet: true, email: true },
    lines: [["Щебень фракции 25–60", 2000, "т", "15000.00", 14]],
  });
  return {
    ...base,
    status: "approved",
    can_decide: false,
    allowed_decisions: [],
    outgoing_number: "ИСХ-027/26",
    steps: [
      step("Директор", "approved", {
        decided_by: DIRECTOR_PERSON,
        decided_at: "2026-10-27T10:00:00Z",
      }),
    ],
  };
}

interface MemoSeed {
  n: number;
  kind: "memo" | "application" | "report";
  prefix: string;
  subject: string;
  text: string;
  author: EdsPerson;
  amount?: string;
  due?: string;
  file?: boolean;
  /** Директор уже согласовал, документ ждёт бухгалтера */
  atAccountant?: boolean;
}

const MEMO_SEEDS: readonly MemoSeed[] = [
  {
    n: 14,
    kind: "memo",
    prefix: "СЗ",
    subject: "Оплата аренды склада за ноябрь",
    text: "Прошу согласовать оплату аренды склада за ноябрь.\nСчёт арендодателя приложен, реквизиты не менялись.",
    author: MANAGER_PERSON,
    amount: "8500000.00",
    due: "2026-10-31",
    file: true,
  },
  {
    n: 3,
    kind: "application",
    prefix: "ЗЯ",
    subject: "Заявление на ежегодный отпуск",
    text: "Прошу предоставить ежегодный отпуск с 10 по 24 ноября.",
    author: SUPPLY_PERSON,
  },
  {
    n: 9,
    kind: "report",
    prefix: "ОТ",
    subject: "Отчёт по остаткам склада за октябрь",
    text: "Остатки на 28 октября сверены с учётом. Расхождений нет, неликвид — 3 позиции.",
    author: SUPPLY_PERSON,
  },
  {
    n: 31,
    kind: "memo",
    prefix: "СЗ",
    subject: "Закупка кофе для офиса",
    text: "Прошу согласовать закупку кофе и расходников для офиса на квартал.",
    author: OFFICE_PERSON,
    amount: "1800000.00",
    due: "2026-11-05",
  },
  {
    n: 15,
    kind: "memo",
    prefix: "СЗ",
    subject: "Оплата командировочных расходов",
    text: "Прошу оплатить командировочные расходы по приложенному авансовому отчёту.",
    author: SUPPLY_PERSON,
    amount: "4200000.00",
    due: "2026-11-03",
    atAccountant: true,
  },
];

function memo(seed: MemoSeed): MemoApprovalCard {
  const number = `${seed.prefix}-2026/${String(seed.n).padStart(3, "0")}`;
  const idTail = String(seed.n).padStart(12, "0");
  return {
    id: `60000000-0000-4000-8000-${idTail}`,
    approval_id: `50000000-0000-4000-8000-${idTail}`,
    number,
    kind: seed.kind,
    subject: seed.subject,
    text: seed.text,
    document_status: seed.atAccountant ? "to_accountant" : "on_approval",
    status: "open",
    round: 1,
    author: seed.author,
    addressee: null,
    amount: seed.amount ? { amount: seed.amount, currency: "UZS" } : null,
    due_date: seed.due ?? null,
    files: seed.file
      ? [
          {
            id: "70000000-0000-4000-8000-000000000001",
            name: "счёт-аренда.pdf",
            content_type: "application/pdf",
            size: 40_960,
          },
        ]
      : [],
    deal: null,
    accountant_step: seed.atAccountant ?? false,
    steps: seed.atAccountant
      ? [
          step("Директор", "approved", {
            decided_by: DIRECTOR_PERSON,
            decided_at: "2026-10-27T12:00:00Z",
          }),
          step("Бухгалтер", "current"),
        ]
      : seed.amount
        ? [step("Директор", "current"), step("Бухгалтер", "pending")]
        : [step("Директор", "current")],
    decisions: [],
    can_decide: true,
    allowed_decisions: ["approve", "return", "reject"],
    created_at: "2026-10-27T10:00:00Z",
    updated_at: "2026-10-27T10:00:00Z",
  };
}

function seedQuotes(): QuoteApprovalCard[] {
  return [...QUOTE_SEEDS.map(quote), approvedQuote()];
}
function seedMemos(): MemoApprovalCard[] {
  return MEMO_SEEDS.map(memo);
}

let quotes = seedQuotes();
let memos = seedMemos();

export const readQuotes = (): QuoteApprovalCard[] => quotes;
export const writeQuotes = (next: QuoteApprovalCard[]): void => {
  quotes = next;
};
export const readMemos = (): MemoApprovalCard[] => memos;
export const writeMemos = (next: MemoApprovalCard[]): void => {
  memos = next;
};
export function resetApprovals(): void {
  quotes = seedQuotes();
  memos = seedMemos();
}

export function findQuote(ref: string): QuoteApprovalCard | undefined {
  return quotes.find((q) => q.id === ref || q.number === ref);
}
export function findMemo(ref: string): MemoApprovalCard | undefined {
  return memos.find((m) => m.id === ref || m.number === ref);
}
