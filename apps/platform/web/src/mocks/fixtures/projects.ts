import type {
  DocumentClientLink,
  ProjectAct,
  ProjectActActionsItem,
  ProjectCard,
  ProjectContract,
  ProjectContractActionsItem,
  ProjectContractTemplate,
  ProjectContractRemark,
  ProjectContractTerm,
  ProjectContractSendBlocker,
  ProjectDeliveryAction,
  ProjectFulfillment,
  ProjectInvoice,
  ProjectJournalEntry,
  ProjectMoney,
  ProjectPerson,
  ProjectRow,
} from "../../shared/api/generated/model";
import { clientRefOf } from "../pictures";

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
  /** ДОК-10: договор собран из утверждённого шаблона; шаги пути и «что мешает» считает `templateOf` из фактов */
  template?: MutableContractTemplate;
  /** Х-1: визы маршрута подписи до отправки клиенту; нет поля — собраны (все прежние проекты уже у клиента). */
  visas?: "none" | "pending" | "returned" | "no_holder" | "collected" | "collecting";
  /** ДС-1: отказ от продления записан (срок считает `termOf` из факта подписи; нет поля — не отказывались). */
  term_declined_by?: "company" | "client";
  /** ДС-1: продлён соглашением — новый срок до этой даты. */
  term_until?: string;
  /** ДП-1: замечания контрагента на согласовании (разбор, ответы); права этого сотрудника — `remarkActions`. */
  remark?: Omit<ProjectContractRemark, "actions" | "awaiting" | "dispute">;
  /** ДП-1: кто ещё должен ответить (имена из мира мока) */
  remark_awaiting?: ProjectPerson[];
}

export interface MutableContractTemplate {
  id: number;
  name: string;
  edition: number;
  deviation: "none" | "requested" | "approved" | "rejected";
  deviation_text: string;
  signed_ours_at: string | null;
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
  fulfillment?: MockFulfillment | null;
  lines?: ProjectCard["delivery_lines"];
}

/** Исполнение в памяти мока: отметки и ссылку на файл считает `toCard` (как ERP и BFF). */
export type MockFulfillment = Omit<
  ProjectFulfillment,
  "actions" | "proof_url" | "goods_not_shipped"
> & {
  goods_not_shipped?: boolean;
};

/** Отметки доставки (L0-1): как `sales/services/delivery_progress.TRANSITIONS` ERP. */
export const DELIVERY_FROM: Record<ProjectDeliveryAction, readonly string[]> = {
  in_transit: ["PENDING", "SHIPPED"],
  delivered: ["PENDING", "SHIPPED", "IN_TRANSIT"],
};

function fulfillmentOf(p: ProjectState, marker: boolean): ProjectFulfillment | null {
  const f = p.fulfillment;
  if (!f) return null;
  const actions = (Object.keys(DELIVERY_FROM) as ProjectDeliveryAction[]).filter(
    (action) => marker && !f.goods_not_shipped && DELIVERY_FROM[action].includes(f.status ?? ""),
  );
  return {
    ...f,
    goods_not_shipped: f.goods_not_shipped ?? false,
    actions,
    proof_url: f.proof_name ? `/api/v1/eds/projects/${numberOf(p)}/delivery/proof` : null,
  };
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
      // Х-1: проект договора готов и визы собраны — его можно отправить клиенту
      id: 111,
      year: 2026,
      title: "Стрелочные переводы",
      client: "ООО «Демо-Рейл»",
      created_at: "2026-10-23T09:00:00+05:00",
      manager: MANAGER,
      total: money("38000000.00"),
      quote: {
        id: 1220,
        number: "КП-2026/121",
        version: 1,
        outgoing: "ИСХ-086/26",
        valid_until: "2026-11-30",
      },
      contract: {
        id: 321,
        number: "ДОГ-2026/111",
        status: "project",
        sent_to_client: false,
        total: money("38000000.00"),
        created_at: "2026-11-20T10:00:00+05:00",
        client_agreed_at: null,
        signed_at: null,
        has_scan: false,
        visas: "collected",
      },
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
      // D2-8: договор выставлен в ЭДО и ждёт скана — строка «Прикрепить скан» в «Моих задачах»
      id: 106,
      year: 2026,
      title: "Путевые знаки",
      client: "АО «Тест-Логистика»",
      created_at: "2026-10-23T09:00:00+05:00",
      manager: OTHER_MANAGER,
      total: money("36400000.00"),
      quote: {
        id: 1215,
        number: "КП-2026/119",
        version: 1,
        outgoing: "ИСХ-084/26",
        valid_until: "2026-11-30",
      },
      contract: {
        id: 314,
        number: "ДОГ-2026/106",
        status: "issued_at_operator",
        sent_to_client: true,
        total: money("36400000.00"),
        created_at: "2026-10-24T10:00:00+05:00",
        client_agreed_at: "2026-10-26T15:00:00+05:00",
        signed_at: null,
        has_scan: false,
      },
      invoices: [],
      act: null,
      journal: [
        entry(
          "contract.issued_external",
          "contract",
          "ДОГ-2026/106",
          "Договор выставлен на подписание",
          "2026-10-27T11:00:00+05:00",
          "Демо Бухгалтеров",
        ),
      ],
    },
    {
      // ДП-1: контрагент прислал замечания и свою редакцию (DOCX); ответили двое, мнения разошлись — решает директор
      id: 112,
      year: 2026,
      title: "Упаковочная линия",
      client: "ООО «Восток Пак»",
      created_at: "2026-11-25T09:00:00+05:00",
      manager: OTHER_MANAGER,
      total: money("412800000.00"),
      quote: {
        id: 1230,
        number: "КП-2026/122",
        version: 1,
        outgoing: "ИСХ-088/26",
        valid_until: "2026-12-05",
      },
      contract: {
        id: 330,
        number: "ДОГ-2026/112",
        status: "project",
        sent_to_client: true,
        total: money("412800000.00"),
        created_at: "2026-11-25T11:40:00+05:00",
        client_agreed_at: null,
        signed_at: null,
        has_scan: false,
        remark: {
          id: 1,
          edition: 1,
          received_at: "2026-11-26T10:02:00+05:00",
          author_name: "Ш. Юсупов",
          comment:
            "Бюджет года закрыт, 50 % сразу не проведём. Склад переехал в Чирчик. Пусконаладку просим включить в цену.",
          file_name: "SC-2026-0012 — редакция контрагента.docx",
          has_file: true,
          summary: {
            changed: ["2.2", "3.1"],
            added: ["3.3"],
            removed: ["5.2"],
            total: 4,
            comparable: true,
          },
          items: [
            {
              point: "2.2",
              kind: "changed",
              ours: "Покупатель вносит предоплату 50 % в течение 5 банковских дней с даты подписания договора.",
              theirs:
                "Покупатель вносит предоплату 30 % в течение 5 банковских дней с даты подписания договора.",
              segments: [
                { op: "equal", text: "Покупатель вносит предоплату " },
                { op: "del", text: "50" },
                { op: "ins", text: "30" },
                { op: "equal", text: " % в течение 5 банковских дней с даты подписания договора." },
              ],
            },
            {
              point: "3.1",
              kind: "changed",
              ours: "Место поставки — склад Покупателя, г. Ташкент.",
              theirs: "Место поставки — склад Покупателя, г. Чирчик, ул. Заводская, 7.",
              segments: [
                { op: "equal", text: "Место поставки — склад Покупателя, " },
                { op: "del", text: "г. Ташкент" },
                { op: "ins", text: "г. Чирчик, ул. Заводская, 7" },
                { op: "equal", text: "." },
              ],
            },
            {
              point: "3.3",
              kind: "added",
              ours: "",
              theirs:
                "Поставщик за свой счёт выполняет пусконаладку оборудования на объекте Покупателя.",
              segments: [],
            },
            {
              point: "5.2",
              kind: "removed",
              ours: "За просрочку оплаты Покупатель уплачивает пеню 0,1 % от суммы долга за каждый день, но не более 10 %.",
              theirs: "",
              segments: [],
            },
          ],
          votes: [
            {
              user: { id: 11, name: "Т. Рахимов" },
              agree: true,
              comment: "Чирчик и 15 дней на остаток нас устраивают.",
              at: "2026-11-26T10:40:00+05:00",
            },
            {
              user: { id: 12, name: "Д. Назаров" },
              agree: false,
              comment: "Пеню в п. 5.2 оставляем. Предоплата — не меньше 40 %.",
              at: "2026-11-26T11:15:00+05:00",
            },
          ],
          deciders: [{ id: 12, name: "Д. Назаров" }],
        },
        remark_awaiting: [],
      },
      invoices: [],
      act: null,
      journal: [
        entry(
          "contract.remark_received",
          "contract",
          "ДОГ-2026/112",
          "Получены замечания контрагента",
          "2026-11-26T10:02:00+05:00",
          null,
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
          "Договор выставлен в ЭДО",
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
      // Отгружено со склада (ОТГ), к клиенту ещё не доехало: дальше — «В пути» и «Доставлено» (L0-1).
      fulfillment: {
        status: "SHIPPED",
        status_name: "Отгружено",
        expected_delivery_date: "2026-10-25",
        shipped_at: "2026-10-22T10:00:00+05:00",
        delivered_at: null,
        accepted_at: null,
        tracking_number: "TRK-4471",
        carrier: "Демо-Логистика",
        proof_name: null,
      },
      lines: [
        {
          line_no: 1,
          title: "Светофор постоянного света",
          quantity: 8,
          unit: "шт",
          status: "shipped",
          eta: "2026-10-25",
          shipped_at: "2026-10-22T10:00:00+05:00",
          tracking: "TRK-4471",
        },
        {
          line_no: 2,
          title: "Монтаж устройств автоблокировки",
          quantity: 1,
          unit: "усл",
          status: "shipped",
          eta: "2026-10-25",
          shipped_at: null,
          tracking: "",
        },
      ],
    },
    {
      // Счёт оплачен, товар отгружен, но не доставлен: акт — после доставки (СЦ-9).
      id: 98,
      year: 2026,
      title: "Светофоры, этап 2",
      client: "ООО «Демо-Сигнал»",
      created_at: "2026-10-13T11:00:00+05:00",
      manager: MANAGER,
      total: money("12800000.00"),
      quote: {
        id: 1195,
        number: "КП-2026/111",
        version: 1,
        outgoing: "ИСХ-071/26",
        valid_until: "2026-11-10",
      },
      contract: {
        id: 302,
        number: "ДОГ-2026/098",
        status: "signed",
        sent_to_client: true,
        total: money("12800000.00"),
        created_at: "2026-10-14T10:00:00+05:00",
        client_agreed_at: "2026-10-15T10:00:00+05:00",
        signed_at: "2026-10-18T12:00:00+05:00",
        has_scan: true,
      },
      invoices: [invoice(4402, "СЧ-2026/132", "paid", "12800000.00")],
      act: null,
      journal: [],
      fulfillment: {
        status: "IN_TRANSIT",
        status_name: "В пути",
        expected_delivery_date: "2026-11-30",
        shipped_at: "2026-11-20T10:00:00+05:00",
        delivered_at: null,
        accepted_at: null,
        tracking_number: "TRK-5120",
        carrier: "Демо-Логистика",
        proof_name: null,
      },
      lines: [],
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
        has_scan: false,
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
          "act.signed",
          "act",
          "АКТ-2026/044",
          "Акт принят заказчиком",
          "2026-10-07T12:00:00+05:00",
          "",
        ),
      ],
    },
  ];
}

let projects: ProjectState[] = seed();
export const readProjects = (): ProjectState[] => projects;

/** Ссылки клиента на документы проектов в Кабинете (ДК-3б): адрес замаскирован, как отдаёт ERP. */
export type MockDocLinkKind = "contract" | "invoice" | "act";
export type MockDocLink = DocumentClientLink;

const docLinkKey = (kind: MockDocLinkKind, id: number) => `${kind}:${String(id)}`;

function seedDocLinks(): Map<string, MockDocLink[]> {
  const link = (
    hint: string,
    sent: string,
    opened: string | null,
    state: MockDocLink["state"] = "active",
  ): MockDocLink => ({
    recipient_hint: hint,
    sent_at: sent,
    first_opened_at: opened,
    last_opened_at: opened,
    expires_at: "2026-12-30T23:59:59+05:00",
    state,
  });
  return new Map<string, MockDocLink[]>([
    [
      docLinkKey("contract", 301),
      [
        link("d***@demo-signal.example", "2026-10-14T10:05:00+05:00", "2026-10-15T09:40:00+05:00"),
        link("b***@demo-signal.example", "2026-10-14T10:05:00+05:00", null),
      ],
    ],
    [
      docLinkKey("invoice", 4401),
      [link("b***@demo-signal.example", "2026-10-19T09:00:00+05:00", null)],
    ],
    [
      docLinkKey("act", 510),
      [link("d***@demo-signal.example", "2026-10-26T09:05:00+05:00", "2026-10-26T14:20:00+05:00")],
    ],
  ]);
}

let docLinks = seedDocLinks();
export const readDocLinks = (kind: MockDocLinkKind, id: number): MockDocLink[] =>
  docLinks.get(docLinkKey(kind, id)) ?? [];
/** Отзыв как в ERP: гасит все живые ссылки документа; повтор ничего не меняет. */
export function revokeDocLinks(kind: MockDocLinkKind, id: number): MockDocLink[] {
  const next = readDocLinks(kind, id).map((l) =>
    l.state === "active" ? { ...l, state: "revoked" as const } : l,
  );
  docLinks.set(docLinkKey(kind, id), next);
  return next;
}
/** Документ в карточке проекта — иначе 404, как у BFF. */
export function ownsDocument(p: ProjectState, kind: MockDocLinkKind, id: number): boolean {
  if (kind === "contract") return p.contract?.id === id;
  if (kind === "act") return p.act?.id === id;
  return p.invoices.some((i) => i.id === id);
}

export function resetProjects(): void {
  projects = seed();
  docLinks = seedDocLinks();
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
    if (status === "client_agreed" || status === "issued_at_operator") return "contract_signing";
    // «Согласуйте редакцию» — только пока проект у клиента; нет договора, не отправлен, отклонён — готовит продавец (СЦ-8).
    return p.contract?.sent_to_client && status !== "rejected"
      ? "contract_review"
      : "contract_preparing";
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

function visasBlocker(
  visas: NonNullable<MutableContract["visas"]> | "collected",
): ProjectContractSendBlocker | null {
  const base = { remark: "", settings_link: false, missing_permissions: [] as string[] };
  switch (visas) {
    case "none":
      return {
        ...base,
        code: "visas_not_requested",
        message:
          "Нужны визы: сначала отправьте договор «На подпись», после виз его можно отправить клиенту.",
        missing: [],
      };
    case "pending":
      return {
        ...base,
        code: "visas_pending",
        message: "Нужны визы: бухгалтер, юрист",
        missing: ["бухгалтер", "юрист"],
        missing_permissions: ["approvals.visa_finance", "approvals.visa_legal"],
      };
    case "collecting":
      // запрос открыт, проекция виз ещё не пришла (событие в пути): ролей в причине нет
      return { ...base, code: "visas_pending", message: "Визы собираются.", missing: [] };
    case "returned":
      return {
        ...base,
        code: "visas_returned",
        message: "Визы возвращены: бухгалтер. Нет графика платежей",
        missing: ["бухгалтер"],
        missing_permissions: ["approvals.visa_finance"],
        remark: "Нет графика платежей",
      };
    case "no_holder":
      return {
        ...base,
        code: "no_visa_holder",
        message:
          "Нет сотрудника для визы: юрист. Назначьте роль в настройках и отправьте договор «На подпись» снова.",
        missing: ["юрист"],
        missing_permissions: ["approvals.visa_legal"],
        settings_link: true,
      };
    default:
      return null;
  }
}

function templateBlocker(code: "CONTRACT_DEVIATION_PENDING" | "CONTRACT_NEEDS_OUR_SIGNATURE") {
  return {
    code,
    message:
      code === "CONTRACT_DEVIATION_PENDING"
        ? "Отступление от шаблона ждёт решения: отправить договор клиенту можно после него."
        : "Нужна наша подпись: по правилам компании договор уходит клиенту подписанным.",
    missing: [] as string[],
    missing_permissions: [] as string[],
    remark: "",
    settings_link: false,
  };
}

/**
 * ОДНА проверка «можно ли отправить проект клиенту» (как `contract_flow.send_blocker` ERP); `null` — можно.
 * По утверждённому шаблону без отступления виз нет, мешает только наша подпись; отступление на решении — своя причина;
 * одобренное отступление и договор вне шаблона идут по визам маршрута (Х-1).
 */
export function sendBlockerOf(c: MutableContract): ProjectContractSendBlocker | null {
  if (c.sent_to_client || c.status !== "project") return null;
  const tpl = c.template;
  if (!tpl) return visasBlocker(c.visas ?? "collected");
  if (tpl.deviation === "requested") return templateBlocker("CONTRACT_DEVIATION_PENDING");
  if (tpl.deviation === "approved") {
    const visas = visasBlocker(c.visas ?? "none");
    if (visas) return visas;
  }
  return tpl.signed_ours_at === null ? templateBlocker("CONTRACT_NEEDS_OUR_SIGNATURE") : null;
}

/** ДП-1: замечания контрагента как их отдаёт ERP: «ждём ответ» и разногласие считаются из ответов, действия — по правам. */
export function remarkOf(c: MutableContract, writer: boolean): ProjectContractRemark | null {
  if (!c.remark || c.status !== "project") return null;
  const awaiting = c.remark_awaiting ?? [];
  const dispute = awaiting.length === 0 && c.remark.votes.some((v) => !v.agree);
  return {
    ...c.remark,
    awaiting,
    dispute,
    actions: writer ? (dispute ? ["vote", "decide"] : ["vote"]) : [],
  };
}

/** Действия по договору, доступные сейчас: допустимо из статуса (таблица ERP) и разрешено правами (`full` — директор, бухгалтер). */
export function contractActions(c: MutableContract, writer: boolean): ProjectContractActionsItem[] {
  if (!writer) return [];
  switch (c.status) {
    case "project":
      if (c.sent_to_client) return ["client_agreed", "reject"];
      return sendBlockerOf(c) ? [] : ["send_to_client"];
    case "client_agreed":
    case "issued_at_operator":
      return ["reject", "attach_scan", "mark_signed"]; // «Ожидает подписания»: скан или заметка (ДП-1)
    case "rejected":
      return ["revise"];
    default:
      return [];
  }
}

/**
 * Блок «договор по шаблону» из фактов (как `crm/services/contract_templates.py`): путь — собран, наша подпись, в Кабинете,
 * подписан обеими; визы нужны только с отступлением. «Что мешает отправить» — одна `sendBlockerOf` (как ERP).
 */
export function templateOf(
  c: MutableContract,
  writer: boolean,
  approver: boolean,
): ProjectContractTemplate | null {
  const tpl = c.template;
  if (!tpl) return null;
  const draft = c.status === "project" && !c.sent_to_client;
  const keys = [
    { key: "assembled", done: true, at: c.created_at },
    { key: "our_signature", done: tpl.signed_ours_at !== null, at: tpl.signed_ours_at },
    { key: "in_cabinet", done: c.sent_to_client, at: c.sent_to_client ? c.created_at : null },
    { key: "signed_both", done: c.status === "signed", at: c.signed_at },
  ] as const;
  let current = false;
  const steps = keys.map((step) => {
    const state: "done" | "current" | "next" = step.done ? "done" : current ? "next" : "current";
    if (!step.done) current = true;
    return { key: step.key, state, at: step.at };
  });
  const actions: ProjectContractTemplate["actions"] = [];
  if (draft && writer) {
    if (tpl.signed_ours_at === null) actions.push("sign_ours");
    if (tpl.deviation !== "requested") actions.push("request_deviation");
  }
  if (draft && tpl.deviation === "requested" && approver) actions.push("decide_deviation");
  return {
    id: tpl.id,
    name: tpl.name,
    edition: tpl.edition,
    deviation: tpl.deviation,
    deviation_text: tpl.deviation_text,
    visas_required: tpl.deviation === "requested" || tpl.deviation === "approved",
    steps,
    actions,
  };
}

/**
 * ДС-1: срок подписанного договора — как ERP (`contract_term.term_card`): до 31 декабря года подписания, продлится сам,
 * отказаться можно за 30 дней до конца; отказ или продление соглашением меняют `term_declined_by` и `term_until`.
 */
export function termOf(c: MutableContract, writer: boolean): ProjectContractTerm | null {
  if (c.status !== "signed" || !c.signed_at) return null;
  const from = c.signed_at.slice(0, 10);
  const until = c.term_until ?? `${from.slice(0, 4)}-12-31`;
  const notice = new Date(`${until}T00:00:00Z`);
  notice.setUTCDate(notice.getUTCDate() - 30);
  const declined = c.term_declined_by ?? null;
  return {
    state: declined ? "ends" : "renews",
    rule: "calendar_year",
    renewal: "auto",
    valid_from: from,
    valid_until: until,
    last_notice_date: notice.toISOString().slice(0, 10),
    notice_days: 30,
    renewals_count: c.term_until ? 1 : 0,
    foreign: false,
    declined_by: declined,
    declined_at: declined ? c.signed_at : null,
    template_edition: c.template?.edition ?? null,
    newer_edition: null,
    confidentiality_years: null,
    trade_secret_indefinite: false,
    actions: writer ? (declined ? ["restore_renewal", "renew"] : ["decline_renewal"]) : [],
  };
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
    ...clientRefOf(p.client),
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
        ? {
            id: c.id,
            number: c.number,
            status: c.status,
            sent_to_client: c.sent_to_client,
            send_blocker_code: sendBlockerOf(c)?.code ?? null,
          }
        : null,
      invoice: last
        ? { id: last.id, number: last.number, status: last.status, count: live.length }
        : null,
      act: p.act
        ? { id: p.act.id, number: p.act.number, status: p.act.status, has_scan: p.act.has_scan }
        : null,
    },
    problems: problemsOf(p),
    created_at: p.created_at,
  };
}

/** Акт — после доставки (СЦ-9): исполнение «Доставлено» или «Принято» — как `billing.act_not_delivered` ERP. */
export function actDelivered(p: ProjectState): boolean {
  return ["DELIVERED", "ACCEPTED"].includes(p.fulfillment?.status ?? "");
}

export function toCard(
  p: ProjectState,
  writer: boolean,
  marker = false,
  approver = false,
): ProjectCard {
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
          template: templateOf(c, writer, approver),
          term: termOf(c, writer),
          remark: remarkOf(c, writer),
          send_blocker: sendBlockerOf(c),
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
    act_blocker: !writer
      ? "forbidden"
      : a
        ? "act_exists"
        : !issuable
          ? "no_invoice"
          : actDelivered(p)
            ? null
            : "not_delivered",
    fulfillment: fulfillmentOf(p, marker),
    delivery_lines: p.lines ?? [],
    journal: p.journal,
  };
}

export { person };
