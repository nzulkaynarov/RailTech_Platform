import type {
  EdsDecision,
  EdsDocumentKind,
  EdsDocumentStatus,
  EdsFile,
  EdsMoney,
  EdsPerson,
  EdsRecipient,
  EdsRegistryKind,
} from "../../shared/api/generated/model";
import { MOCK_USER_CRM_ID } from "./approvals";
import { DEMO_USERS } from "./users";

/**
 * Состояние моков «EDS · Создать документ и Мои документы» (D1-5, BFF 0.16.0): документы сотрудников, строки реестра
 * (письма, КП), загруженные файлы, заявки для «Связи с проектом». Данные выдуманы. Хранится в `localStorage` страницы
 * (обработчики MSW работают в потоке страницы), поэтому переживает перезагрузку; без хранилища — в памяти.
 */
export const EDS_MOCK_NOW = "2026-10-27T09:00:00Z";
const EARLIER = "2026-10-26T08:30:00Z";
const KEY = "rt-pf-mock-eds-documents";

export interface MockDocument {
  id: string;
  kind: EdsDocumentKind;
  number: string | null;
  status: EdsDocumentStatus;
  version: number;
  subject: string;
  text: string;
  /** Демо-пользователь Платформы, создавший документ */
  ownerId: string;
  amount: EdsMoney | null;
  due_date: string | null;
  file_ids: string[];
  erp_deal_id: number | null;
  recipient: EdsRecipient | null;
  decisions: EdsDecision[];
  created_at: string;
  updated_at: string;
}

/** Строка реестра, которой нет среди документов сотрудников: входящее письмо или КП (откроются в своих разделах). */
export interface MockRegistryRow {
  kind: Extract<EdsRegistryKind, "letter_in" | "quote" | "contract" | "invoice" | "act">;
  id: string;
  number: string;
  title: string;
  status: string;
  registered_at: string;
  responsible: EdsPerson | null;
  /** Договор, счёт и акт проекта: id сделки для ссылки на карточку проекта (0.26.0) */
  project_ref?: string;
}

export interface MockDeal {
  erp_deal_id: number;
  number: string;
  title: string;
  company: string;
}

export interface EdsMock {
  documents: MockDocument[];
  registry: MockRegistryRow[];
  files: Record<string, EdsFile>;
  /** Ключ повтора создания -> id созданного документа (как у EDS: повтор отдаёт прежний ответ) */
  idempotency?: Record<string, string>;
  next: { doc: number; memo: number; application: number; report: number; outgoing: number };
}

export const MOCK_DEALS: readonly MockDeal[] = [
  {
    erp_deal_id: 904,
    number: "ЗВ-2026-104",
    title: "Поставка рельсов Р65",
    company: "ООО «Демо-Путь»",
  },
  {
    erp_deal_id: 905,
    number: "ЗВ-2026-105",
    title: "Монтаж стрелочных переводов",
    company: "АО «Пример-Рельс»",
  },
  {
    erp_deal_id: 898,
    number: "ПР-2026-098",
    title: "Ремонт путей станции Север",
    company: "ООО «Условная станция»",
  },
];

/** Числовой `crm_user_id` демо-сотрудника: порядковый номер в списке демо-пользователей. */
export function crmUserId(ownerId: string): number {
  return DEMO_USERS.findIndex((user) => user.id === ownerId) + 1;
}

export function personOf(ownerId: string): EdsPerson {
  const user = DEMO_USERS.find((candidate) => candidate.id === ownerId);
  return { crm_user_id: crmUserId(ownerId), full_name: user?.name ?? "Сотрудник" };
}

export const DIRECTOR: EdsPerson = { crm_user_id: 2, full_name: "Демо Директоров" };
export const ACCOUNTANT: EdsPerson = { crm_user_id: 5, full_name: "Демо Бухгалтеров" };

export function documentId(n: number): string {
  return `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
}

function memo(
  n: number,
  over: Partial<MockDocument> & Pick<MockDocument, "subject">,
): MockDocument {
  return {
    id: documentId(n),
    kind: "memo",
    number: null,
    status: "draft",
    version: 1,
    text: "Прошу рассмотреть вопрос и принять решение (вымышленный пример).",
    ownerId: "u-demo-manager",
    amount: null,
    due_date: null,
    file_ids: [],
    erp_deal_id: null,
    recipient: null,
    decisions: [],
    created_at: EARLIER,
    updated_at: EDS_MOCK_NOW,
    ...over,
  };
}

function initial(): EdsMock {
  return {
    documents: [
      memo(1, {
        number: "СЗ-2026/031",
        subject: "Закупка канцтоваров на квартал",
        text: "Прошу согласовать закупку канцтоваров для отдела продаж на IV квартал. Счёт поставщика приложен.",
        status: "on_approval",
        amount: { amount: "4800000.00", currency: "UZS" },
        due_date: "2026-11-05",
        file_ids: [documentId(901)],
        created_at: "2026-10-26T08:30:00Z",
      }),
      memo(2, {
        number: "СЗ-2026/028",
        subject: "Командировка в Самарканд",
        text: "Прошу согласовать командировку на переговоры с клиентом на 3 дня.",
        status: "returned",
        decisions: [
          {
            round: 1,
            step: 1,
            decision: "return",
            comment: "Добавьте смету расходов.",
            by: DIRECTOR,
            at: "2026-10-25T14:10:00Z",
          },
        ],
        created_at: "2026-10-24T09:00:00Z",
      }),
      memo(3, {
        kind: "application",
        number: "ЗЯ-2026/012",
        subject: "Заявление на ежегодный отпуск",
        text: "Прошу предоставить ежегодный оплачиваемый отпуск с 9 по 20 ноября.",
        status: "approved",
        decisions: [
          {
            round: 1,
            step: 1,
            decision: "approve",
            comment: null,
            by: DIRECTOR,
            at: "2026-10-22T10:30:00Z",
          },
        ],
        created_at: "2026-10-21T09:00:00Z",
      }),
      memo(4, {
        number: "СЗ-2026/033",
        subject: "Ремонт кондиционера в переговорной",
        text: "Нужно заменить компрессор в кондиционере переговорной комнаты.",
        status: "draft",
        amount: { amount: "1200000.00", currency: "UZS" },
        created_at: "2026-10-27T07:45:00Z",
      }),
      memo(5, {
        kind: "report",
        number: "ОТ-2026/007",
        subject: "Итоги недели по заявкам",
        text: "За неделю получено 14 заявок, 9 переданы в расчёт, 3 ждут резолюции.",
        status: "draft",
        ownerId: "u-demo-director",
        created_at: "2026-10-26T16:00:00Z",
      }),
      memo(6, {
        number: "СЗ-2026/030",
        subject: "Заказ спецодежды для бригады",
        text: "Прошу согласовать закупку комплектов спецодежды для монтажной бригады.",
        status: "to_accountant",
        ownerId: "u-demo-supply",
        amount: { amount: "9600000.00", currency: "UZS" },
        decisions: [
          {
            round: 1,
            step: 1,
            decision: "approve",
            comment: null,
            by: DIRECTOR,
            at: "2026-10-26T12:00:00Z",
          },
        ],
        created_at: "2026-10-25T11:00:00Z",
      }),
    ],
    registry: [
      {
        kind: "letter_in",
        id: documentId(701),
        number: "ВХ-104/26",
        title: "Запрос цен на рельсы Р65",
        status: "awaiting_resolution",
        registered_at: "2026-10-26T13:20:00Z",
        responsible: { crm_user_id: 1, full_name: "Демо Менеджеров" },
      },
      {
        kind: "quote",
        id: documentId(801),
        number: "КП-2026/115",
        title: "КП · Монтаж стрелочных переводов",
        status: "open",
        registered_at: "2026-10-25T15:00:00Z",
        responsible: DIRECTOR,
      },
      {
        kind: "contract",
        id: documentId(811),
        number: "ДОГ-2026/105",
        title: "Поставка стрелочных переводов",
        status: "client_agreed",
        registered_at: "2026-10-24T09:00:00Z",
        responsible: { crm_user_id: 1, full_name: "Демо Менеджеров" },
        project_ref: "105",
      },
      {
        kind: "act",
        id: documentId(812),
        number: "АКТ-2026/051",
        title: "Монтаж крепежа, объект «Север»",
        status: "issued",
        registered_at: "2026-10-23T09:00:00Z",
        responsible: { crm_user_id: 1, full_name: "Демо Менеджеров" },
        project_ref: "97",
      },
    ],
    files: {
      [documentId(901)]: {
        id: documentId(901),
        name: "schet-kanctovary.pdf",
        content_type: "application/pdf",
        size: 184_320,
      },
    },
    next: { doc: 100, memo: 34, application: 13, report: 8, outgoing: 82 },
  };
}

/** Служебка на согласовании, как её видит директор (`MemoApprovalCard`): ровно те поля, что нужны документу автора. */
export interface ReturnedSource {
  id: string;
  number: string | null;
  kind: EdsDocumentKind;
  subject: string;
  text: string;
  amount: EdsMoney | null;
  due_date: string | null;
  author: EdsPerson;
}

/**
 * Согласующий вернул документ на доработку (D1-6b): в документах автора он получает статус «Возвращён на доработку» и
 * решение «Вернуть» с комментарием, как это делает EDS, — по нему автор видит в «Моих задачах» строку «Доработать» и открывает
 * «Продолжить». Автор не демо-пользователь Платформы (офис-менеджер без входа) — записывать некому.
 */
export function recordReturn(source: ReturnedSource, decision: EdsDecision): void {
  const ownerId = Object.entries(MOCK_USER_CRM_ID).find(
    ([, crmId]) => crmId === source.author.crm_user_id,
  )?.[0];
  if (!ownerId) return;
  const state = readEds();
  const found = state.documents.find((doc) => doc.number === source.number);
  if (found) {
    found.status = "returned";
    found.decisions = [...found.decisions, decision];
    found.updated_at = decision.at;
  } else {
    state.documents.push({
      id: source.id,
      kind: source.kind,
      number: source.number,
      status: "returned",
      version: 1,
      subject: source.subject,
      text: source.text,
      ownerId,
      amount: source.amount,
      due_date: source.due_date,
      file_ids: [],
      erp_deal_id: null,
      recipient: null,
      decisions: [decision],
      created_at: EARLIER,
      updated_at: decision.at,
    });
  }
  writeEds(state);
}

let memory: EdsMock | null = null;

export function readEds(): EdsMock {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as EdsMock;
  } catch {
    if (memory) return structuredClone(memory);
  }
  return initial();
}

export function writeEds(state: EdsMock): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetEds(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}
