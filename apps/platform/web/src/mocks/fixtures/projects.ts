import type {
  ProjectAct,
  ProjectActActionsItem,
  ProjectCard,
  ProjectContract,
  ProjectContractActionsItem,
  ProjectInvoice,
  ProjectJournalEntry,
  ProjectMoney,
  ProjectPerson,
  ProjectRow,
} from "../../shared/api/generated/model";

/**
 * Вымышленные проекты для MSW (D2-5, BFF 0.26.0): те же формы, что вернёт BFF по `platform-bff.yaml`; поведение переходов
 * повторяет ERP (`crm/services/contract_flow.py`, `act_flow.py`, `projects.py`). Названия компаний и имена выдуманы
 * (репозиторий публичный). Состояние живёт в памяти страницы: действие меняет документ, и следующий запрос его видит;
 * `resetProjects()` возвращает исходное (тесты).
 */
const money = (amount: string): ProjectMoney => ({ amount, currency: "UZS" });
const person = (id: number, name: string): ProjectPerson => ({ id, name });
export const MANAGER = person(2, "Демо Менеджеров");
export const OTHER_MANAGER = person(7, "Демо Помощников");
export const ACCOUNTANT = person(51, "Демо Бухгалтеров");
export const DIRECTOR = person(1, "Демо Директоров");
/** Сотрудник сессии мока -> id сотрудника ERP (фильтр «мои») */
export const MOCK_STAFF_ID: Record<string, number> = {
  "u-demo-manager": 2,
  "u-demo-director": 1,
  "u-demo-accountant": 51,
};

type ContractWord = ProjectContract["status"];
type ActWord = ProjectAct["status"];

interface MutableContract {
  id: number;
  number: string;
  status: ContractWord;
  sent_to_client: boolean;
  total: ProjectMoney;
  created_at: string;
  client_agreed_at: string | null;
  signed_at: string | null;
  has_scan: boolean;
}

interface MutableAct {
  id: number;
  number: string;
  status: ActWord;
  total: ProjectMoney;
  issued_at: string | null;
  signed_at: string | null;
  rejection_reason: string;
  has_scan: boolean;
}

export interface ProjectState {
  id: number;
  year: number;
  title: string;
  client: string;
  created_at: string;
  manager: ProjectPerson;
  total: ProjectMoney;
  quote: { id: number; number: string; version: number; outgoing: string; valid_until: string };
  contract: MutableContract | null;
  invoices: ProjectInvoice[];
  act: MutableAct | null;
  journal: ProjectJournalEntry[];
  fulfillment?: ProjectCard["fulfillment"];
  lines?: ProjectCard["delivery_lines"];
}

const entry = (
  code: string,
  document: ProjectJournalEntry["document"],
  number: string,
  text: string,
  at: string,
  actor: string | null,
  reason = "",
): ProjectJournalEntry => ({ at, code, text, actor_name: actor, document, number, reason });

function invoice(
  id: number,
  number: string,
  status: ProjectInvoice["status"],
  amount: string,
): ProjectInvoice {
  const paid = status === "paid" ? amount : "0.00";
  return {
    id,
    number,
    status,
    total: money(amount),
    paid: money(paid),
    balance_due: money(status === "paid" ? "0.00" : amount),
    issued_at: "2026-10-24",
    due_date: status === "overdue" ? "2026-10-20" : "2026-11-07",
    has_pdf: true,
  };
}

function seed(): ProjectState[] {
  return [
    {
      id: 104,
      year: 2026,
      title: "Стрелочные приводы",
      client: "ООО «Демо-Рейл»",
      created_at: "2026-10-20T09:20:00+05:00",
      manager: MANAGER,
      total: money("125000000.00"),
      quote: {
        id: 1203,
        number: "КП-2026/115",
        version: 2,
        outgoing: "ИСХ-082/26",
        valid_until: "2026-11-27",
      },
      // КП принято, проект договора ещё не сформирован: бухгалтер создаёт его кнопкой
      contract: null,
      invoices: [],
      act: null,
      journal: [],
    },
    {
      id: 105,
      year: 2026,
      title: "Рельсовые скрепления",
      client: "АО «Демо-Транс»",
      created_at: "2026-10-21T10:00:00+05:00",
      manager: OTHER_MANAGER,
      total: money("56000000.00"),
      quote: {
        id: 1210,
        number: "КП-2026/116",
        version: 1,
        outgoing: "ИСХ-083/26",
        valid_until: "2026-11-28",
      },
      contract: {
        id: 312,
        number: "ДОГ-2026/105",
        status: "project",
        sent_to_client: true,
        total: money("56000000.00"),
        created_at: "2026-10-22T10:00:00+05:00",
        client_agreed_at: null,
        signed_at: null,
        has_scan: false,
      },
      invoices: [],
      act: null,
      journal: [
        entry(
          "contract.sent_to_client",
          "contract",
          "ДОГ-2026/105",
          "Проект договора отправлен клиенту на согласование",
          "2026-10-22T10:05:00+05:00",
          "Демо Бухгалтеров",
        ),
      ],
    },
    {
      id: 97,
      year: 2026,
      title: "Автоблокировка, этап 1",
      client: "ООО «Демо-Сигнал»",
      created_at: "2026-10-12T11:00:00+05:00",
      manager: MANAGER,
      total: money("89600000.00"),
      quote: {
        id: 1190,
        number: "КП-2026/110",
        version: 1,
        outgoing: "ИСХ-070/26",
        valid_until: "2026-11-10",
      },
      contract: {
        id: 301,
        number: "ДОГ-2026/097",
        status: "signed",
        sent_to_client: true,
        total: money("89600000.00"),
        created_at: "2026-10-14T10:00:00+05:00",
        client_agreed_at: "2026-10-15T10:00:00+05:00",
        signed_at: "2026-10-18T12:00:00+05:00",
        has_scan: true,
      },
      invoices: [invoice(4401, "СЧ-2026/131", "paid", "89600000.00")],
      act: {
        id: 510,
        number: "АКТ-2026/051",
        status: "issued",
        total: money("89600000.00"),
        issued_at: "2026-10-26",
        signed_at: null,
        rejection_reason: "",
        has_scan: false,
      },
      journal: [
        entry(
          "act.issued",
          "act",
          "АКТ-2026/051",
          "Акт выпущен",
          "2026-10-26T09:00:00+05:00",
          "Демо Бухгалтеров",
        ),
        entry(
          "contract.scan_attached",
          "contract",
          "ДОГ-2026/097",
          "Прикреплён скан подписанного договора",
          "2026-10-18T12:00:00+05:00",
          "Демо Бухгалтеров",
        ),
        entry(
          "contract.issued_external",
          "contract",
          "ДОГ-2026/097",
          "Договор выставлен у оператора",
          "2026-10-16T10:00:00+05:00",
          "Демо Бухгалтеров",
        ),
        entry(
          "contract.client_agreed",
          "contract",
          "ДОГ-2026/097",
          "Редакция договора согласована клиентом",
          "2026-10-15T10:00:00+05:00",
          "Демо Бухгалтеров",
        ),
      ],
      fulfillment: {
        status: "DELIVERED",
        status_name: "Доставлено",
        expected_delivery_date: "2026-10-25",
        shipped_at: "2026-10-22T10:00:00+05:00",
        delivered_at: "2026-10-25T15:00:00+05:00",
        accepted_at: null,
        tracking_number: "TRK-4471",
        carrier: "Демо-Логистика",
      },
      lines: [
        {
          line_no: 1,
          title: "Светофор постоянного света",
          quantity: 8,
          unit: "шт",
          status: "delivered",
          eta: "2026-10-25",
          shipped_at: "2026-10-22T10:00:00+05:00",
          tracking: "TRK-4471",
        },
        {
          line_no: 2,
          title: "Монтаж устройств автоблокировки",
          quantity: 1,
          unit: "усл",
          status: "delivered",
          eta: "2026-10-25",
          shipped_at: null,
          tracking: "",
        },
      ],
    },
    {
      id: 81,
      year: 2026,
      title: "Кабель СБ",
      client: "ООО «Демо-Кабель»",
      created_at: "2026-10-05T08:30:00+05:00",
      manager: MANAGER,
      total: money("42000000.00"),
      quote: {
        id: 1170,
        number: "КП-2026/104",
        version: 1,
        outgoing: "ИСХ-061/26",
        valid_until: "2026-11-05",
      },
      contract: {
        id: 290,
        number: "ДОГ-2026/081",
        status: "rejected",
        sent_to_client: true,
        total: money("42000000.00"),
        created_at: "2026-10-07T10:00:00+05:00",
        client_agreed_at: null,
        signed_at: null,
        has_scan: false,
      },
      invoices: [],
      act: null,
      journal: [
        entry(
          "contract.rejected",
          "contract",
          "ДОГ-2026/081",
          "Договор отклонён клиентом",
          "2026-10-09T10:00:00+05:00",
          "Демо Бухгалтеров",
          "Неустойка 0,5 % в день слишком велика",
        ),
        entry(
          "contract.sent_to_client",
          "contract",
          "ДОГ-2026/081",
          "Проект договора отправлен клиенту на согласование",
          "2026-10-07T10:30:00+05:00",
          "Демо Бухгалтеров",
        ),
      ],
    },
    {
      id: 72,
      year: 2026,
      title: "Подшипники буксовые",
      client: "ООО «Демо-Рейл»",
      created_at: "2026-09-18T09:00:00+05:00",
      manager: MANAGER,
      total: money("18000000.00"),
      quote: {
        id: 1100,
        number: "КП-2026/090",
        version: 1,
        outgoing: "ИСХ-051/26",
        valid_until: "2026-10-18",
      },
      contract: {
        id: 270,
        number: "ДОГ-2026/072",
        status: "signed",
        sent_to_client: true,
        total: money("18000000.00"),
        created_at: "2026-09-20T10:00:00+05:00",
        client_agreed_at: "2026-09-21T10:00:00+05:00",
        signed_at: "2026-09-24T12:00:00+05:00",
        has_scan: true,
      },
      invoices: [invoice(4300, "СЧ-2026/118", "paid", "18000000.00")],
      act: {
        id: 480,
        number: "АКТ-2026/044",
        status: "signed",
        total: money("18000000.00"),
        issued_at: "2026-10-05",
        signed_at: "2026-10-07T12:00:00+05:00",
        rejection_reason: "",
        has_scan: true,
      },
      journal: [
        entry(
          "project.done",
          "project",
          "",
          "Проект выполнен",
          "2026-10-07T12:00:00+05:00",
          "Демо Бухгалтеров",
        ),
        entry(
          "act.scan_attached",
          "act",
          "АКТ-2026/044",
          "Прикреплён скан подписанного акта",
          "2026-10-07T12:00:00+05:00",
          "Демо Бухгалтеров",
        ),
      ],
    },
  ];
}

let projects: ProjectState[] = seed();
export const readProjects = (): ProjectState[] => projects;
export function resetProjects(): void {
  projects = seed();
}
export function writeProject(next: ProjectState): void {
  projects = projects.map((p) => (p.id === next.id ? next : p));
}
export function findProject(ref: string): ProjectState | undefined {
  const text = decodeURIComponent(ref).trim();
  if (/^\d+$/.test(text)) return projects.find((p) => p.id === Number(text));
  const found = /^(?:ПР|ЗВ)-(\d{4})-(\d+)$/i.exec(text);
  if (!found) return undefined;
  return projects.find((p) => p.id === Number(found[2]) && p.year === Number(found[1]));
}

export const numberOf = (p: Pick<ProjectState, "id" | "year">, prefix = "ПР"): string =>
  `${prefix}-${String(p.year)}-${String(p.id).padStart(3, "0")}`;

// --- производные значения (как в ERP) --------------------------------------------------------------------

export function isDone(p: ProjectState): boolean {
  const billable = p.invoices.filter((i) => i.status !== "to_issue" && i.status !== "cancelled");
  if (billable.length === 0 || billable.some((i) => i.status !== "paid")) return false;
  return p.act !== null && p.act.status === "signed";
}

export function stepOf(p: ProjectState): ProjectRow["step"] {
  if (isDone(p)) return "DONE";
  return p.contract?.status === "signed" ? "PAYMENT" : "CONTRACT";
}

export function clientStatusOf(p: ProjectState): ProjectRow["client_status"] {
  const step = stepOf(p);
  if (step === "DONE") return "done";
  if (step === "CONTRACT") {
    const status = p.contract?.status;
    return status === "client_agreed" || status === "issued_at_operator"
      ? "contract_signing"
      : "contract_review";
  }
  if (p.act?.status === "issued") return "awaiting_acceptance";
  if (
    p.invoices.some(
      (i) => i.status !== "paid" && i.status !== "to_issue" && i.status !== "cancelled",
    )
  ) {
    return "awaiting_payment";
  }
  return "fulfilling";
}

export function problemsOf(p: ProjectState): ProjectRow["problems"] {
  const problems: ProjectRow["problems"] = [];
  if (!p.contract) problems.push("no_contract");
  else if (p.contract.status === "rejected") problems.push("contract_rejected");
  if (p.act?.status === "returned") problems.push("act_returned");
  if (p.invoices.some((i) => i.status === "overdue")) problems.push("invoice_overdue");
  return problems;
}

/** Действия по договору, доступные сейчас: допустимо из статуса (таблица ERP) и разрешено правами (`full` — директор, бухгалтер). */
export function contractActions(c: MutableContract, writer: boolean): ProjectContractActionsItem[] {
  if (!writer) return [];
  switch (c.status) {
    case "project":
      return c.sent_to_client ? ["client_agreed", "reject"] : ["send_to_client"];
    case "client_agreed":
      return ["mark_issued", "reject"];
    case "issued_at_operator":
      return ["attach_scan", "reject"];
    case "rejected":
      return ["revise"];
    default:
      return [];
  }
}

export function actActions(a: MutableAct, writer: boolean): ProjectActActionsItem[] {
  if (!writer) return [];
  if (a.status === "issued") return ["attach_scan", "return"];
  if (a.status === "returned") return ["reissue"];
  return [];
}

function historyOf(p: ProjectState, document: "contract" | "act"): ProjectJournalEntry[] {
  return p.journal.filter((e) => e.document === document);
}

export function toRow(p: ProjectState): ProjectRow {
  const c = p.contract;
  const live = p.invoices.filter((i) => i.status !== "cancelled");
  const last = live.length > 0 ? live[live.length - 1] : undefined;
  const fulfillmentEta = p.fulfillment?.expected_delivery_date ?? null;
  return {
    number: numberOf(p),
    request_number: numberOf(p, "ЗВ"),
    title: p.title,
    client_name: p.client,
    step: stepOf(p),
    client_status: clientStatusOf(p),
    total: p.total,
    due_date: fulfillmentEta,
    manager: p.manager,
    responsible: p.manager,
    documents: {
      quote: {
        id: p.quote.id,
        number: p.quote.number,
        status: "accepted",
        version: p.quote.version,
      },
      contract: c
        ? { id: c.id, number: c.number, status: c.status, sent_to_client: c.sent_to_client }
        : null,
      invoice: last
        ? { id: last.id, number: last.number, status: last.status, count: live.length }
        : null,
      act: p.act ? { id: p.act.id, number: p.act.number, status: p.act.status } : null,
    },
    problems: problemsOf(p),
    created_at: p.created_at,
  };
}

export function toCard(p: ProjectState, writer: boolean): ProjectCard {
  const c = p.contract;
  const a = p.act;
  const issuable = p.invoices.some((i) =>
    ["issued", "partial", "paid", "overdue"].includes(i.status),
  );
  return {
    ...toRow(p),
    quote: {
      id: p.quote.id,
      number: p.quote.number,
      status: "accepted",
      version: p.quote.version,
      outgoing_number: p.quote.outgoing,
      valid_until: p.quote.valid_until,
    },
    contract: c
      ? {
          id: c.id,
          number: c.number,
          status: c.status,
          sent_to_client: c.sent_to_client,
          total: c.total,
          created_at: c.created_at,
          client_agreed_at: c.client_agreed_at,
          signed_at: c.signed_at,
          has_pdf: true,
          has_scan: c.has_scan,
          actions: contractActions(c, writer),
          history: historyOf(p, "contract"),
        }
      : null,
    can_create_contract: writer && c === null,
    invoices: p.invoices,
    act: a
      ? {
          id: a.id,
          number: a.number,
          status: a.status,
          total: a.total,
          issued_at: a.issued_at,
          signed_at: a.signed_at,
          rejection_reason: a.rejection_reason,
          has_pdf: true,
          has_scan: a.has_scan,
          actions: actActions(a, writer),
          history: historyOf(p, "act"),
        }
      : null,
    act_blocker: !writer ? "forbidden" : a ? "act_exists" : issuable ? null : "no_invoice",
    fulfillment: p.fulfillment ?? null,
    delivery_lines: p.lines ?? [],
    journal: p.journal,
  };
}

export { person };
