import type {
  QueueCategory,
  QueueItem,
  QueueItemKind,
  WaitingRow,
} from "../shared/api/generated/model";
import type { MockRole } from "./fixtures/roles";

/**
 * ГЛ-1, как у BFF (`feeds/queue_meta.py`): группа из срока, вид работы, глагол кнопки и «почему у вас», если источник мока
 * своего не задал. Демо-строки остаются короткими, а экран и тесты видят те же поля, что даст BFF.
 */
const CATEGORY: Partial<Record<QueueItemKind, QueueCategory>> = {
  sign_document: "sign",
  approve_quote: "approve",
  approve_memo: "approve",
  resolve_letter: "resolution",
  instruction: "instruction",
  instruction_extension: "instruction",
  acquaint: "instruction",
  pay_memo: "payment",
  confirm_payment: "payment",
  issue_invoice: "payment",
  overdue_invoice: "payment",
  answer_lead: "lead",
  take_lead: "lead",
  triage_lead: "lead",
  inbound_mail: "mail",
  inbound_mail_mine: "mail",
  supplier_overdue: "supply",
  send_supplier_order: "supply",
  partner_date_change: "supply",
  receive_goods: "supply",
  partner_application: "supply",
  order_shortage: "supply",
  ship_project: "supply",
  calc_task: "project",
  issue_contract: "project",
  attach_scan: "project",
  issue_act: "project",
};

const ACTION: Partial<Record<QueueItemKind, string>> = {
  sign_document: "Подписать",
  approve_quote: "Одобрить",
  approve_memo: "Согласовать",
  pay_memo: "Принять к оплате",
  resolve_letter: "Наложить резолюцию",
  instruction: "Исполнить",
  instruction_extension: "Решить",
  acquaint: "Ознакомлен",
  rework_document: "Доработать",
  answer_lead: "Ответить",
  take_lead: "Взять",
  triage_lead: "Разобрать",
  calc_task: "Рассчитать",
  confirm_payment: "Подтвердить",
  issue_invoice: "Выставить",
};

const REASON: Partial<Record<QueueItemKind, string>> = {
  sign_document: "вы подписант по реестру полномочий",
  approve_quote: "ваш шаг одобрения КП",
  approve_memo: "вы согласующий по маршруту",
  pay_memo: "ваш шаг: принять к оплате",
  resolve_letter: "входящее без резолюции",
  instruction: "резолюция от 18.11 · вы ответственный",
  instruction_extension: "вы автор резолюции",
  acquaint: "вас просят ознакомиться с письмом · без срока",
  rework_document: "вам вернули документ на доработку",
  answer_lead: "ваш клиент ждёт ответа",
  take_lead: "лид без менеджера",
  triage_lead: "вы первая линия по лидам",
  supplier_overdue: "заказ поставщику просрочен",
};

export function withQueueMeta(item: QueueItem): QueueItem {
  const reason = item.reason ?? REASON[item.kind] ?? "по вашей роли";
  return {
    ...item,
    reason:
      item.on_behalf_of && !item.reason
        ? `вы замещаете ${item.on_behalf_of.name} · ${reason}`
        : reason,
    group:
      item.group ??
      (item.due_label === "overdue"
        ? "overdue"
        : item.due_label === "today" && item.due_at
          ? "today"
          : "later"),
    category: item.category ?? CATEGORY[item.kind] ?? "other",
    action_label: item.action_label ?? ACTION[item.kind],
  };
}

const HOUR = 3_600_000;
/** Когда по объекту уже напоминали (мок «не чаще раза в час»). */
const reminded = new Map<string, number>();

export function remindedAt(id: string): number | undefined {
  return reminded.get(id);
}

export function markReminded(id: string, at = Date.now()): void {
  reminded.set(id, at);
}

export function resetReminded(): void {
  reminded.clear();
}

/**
 * «Вы ждёте других»: демо у ролей, которые передают дела (подписанту, согласующему и исполнителю). Роль без раздела
 * решений ничего не ждёт.
 */
export function waitingForView(view: readonly MockRole[], now = Date.now()): WaitingRow[] {
  const passes = view.some((role) => role.demo === "MANAGER" || role.demo === "DIRECTOR");
  if (!passes) return [];
  const rows: WaitingRow[] = [
    {
      id: "letter_signature:90000000-0000-4000-8000-000000000001",
      kind: "letter_signature",
      object_id: "90000000-0000-4000-8000-000000000001",
      title: "Ответ на требование",
      waiting_on: { id: "4", name: "Рустам Каримов" },
      since: new Date(now - 3 * HOUR).toISOString(),
      remindable: true,
      object: {
        kind: "memo",
        number: "Ответ на требование",
        path: "/eds/documents?scope=all&doc=90000000-0000-4000-8000-000000000001&panel=open",
      },
    },
    {
      id: "approval:90000000-0000-4000-8000-000000000002",
      kind: "approval",
      object_id: "90000000-0000-4000-8000-000000000002",
      title: "СЗ-2026/212 · Закупка канцтоваров",
      waiting_label: "Бухгалтер",
      since: new Date(now - 26 * HOUR).toISOString(),
      remindable: true,
      object: {
        kind: "memo",
        number: "СЗ-2026/212",
        path: "/eds/approvals/%D0%A1%D0%97-2026%2F212?panel=open&tab=agree",
      },
    },
  ];
  return rows.map((row) => {
    const last = reminded.get(row.object_id);
    return last !== undefined && now - last < HOUR
      ? {
          ...row,
          remindable: false,
          remind_available_at: new Date(last + HOUR).toISOString(),
        }
      : row;
  });
}
