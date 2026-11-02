import type {
  MenuCounter,
  ObjectRef,
  PaymentCard,
  ProjectRow,
  QueueCard,
  QueueItem,
} from "../shared/api/generated/model";
import { QUEUE, allows } from "../app/rbac.generated";
import { type MockCalcRow, myCalcRows } from "./erpCalc";
import { companyToday, readInvoices } from "./fixtures/payments";
import { readProjects, toRow } from "./fixtures/projects";
import type { MockRole } from "./fixtures/roles";
import { readSession, sessionRoles } from "./mockSession";

/**
 * «Мои задачи»: работа ERP (D2-8) — те же правила, что у BFF (`bff/app/feeds/erp_work.py`), поверх тех же демо-складов, что
 * экраны «Расчёт», «Счета и оплаты» и «Проекты»: действие на экране меняет очередь, счётчики меню и карточки (U1: моки не
 * задают числа вручную). Вид строки — по секции `queue` каталога; одна строка на действие, у совмещённой роли дублей нет.
 */
type Kind = QueueItem["kind"];

const seg = (value: string) => encodeURIComponent(value);
const NBSP = " ";

function money(amount: string, currency: string): string {
  const value = Number(amount);
  const whole = Number.isInteger(value);
  const shown = (whole ? String(value) : value.toFixed(2))
    .replace(".", ",")
    .replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return `${shown}${NBSP}${currency === "UZS" ? "сум" : currency}`;
}

const join = (...parts: (string | null | undefined)[]) => parts.filter(Boolean).join(" · ");

/**
 * Роли исполнения — роли «вида» без системной роли DIRECTOR (решение архитектора 2026-11-02, как `feeds/work_roles.py`
 * BFF): в очереди директора только решения, исполнение ERP — у ролей из шаблона и созданных ролей по каталогу.
 */
function executors(view: readonly MockRole[]): MockRole[] {
  return view.filter((role) => !(role.system && role.code === "DIRECTOR"));
}

function roleFor(view: readonly MockRole[], kind: Kind): MockRole | undefined {
  const need = QUEUE[kind];
  return executors(view).find((role) => allows(role.access, need.resource, need.level));
}

function full(view: readonly MockRole[], resource: string): boolean {
  return executors(view).some((role) => role.access[resource] === "full");
}

function userName(): string | null {
  const session = readSession();
  return session ? (sessionRoles(session)?.user.name ?? null) : null;
}

/** Бейдж срока по календарю компании, как `due_label` BFF: прошёл — просрочено, сегодня, завтра, иначе — дата. */
function dueLabel(due: string): QueueItem["due_label"] {
  const today = companyToday();
  if (due < today) return "overdue";
  if (due === today) return "today";
  const next = new Date(`${today}T12:00:00Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  return due === next.toISOString().slice(0, 10) ? "tomorrow" : "later";
}

// --- расчёт ------------------------------------------------------------------------------------

function calcAction(row: MockCalcRow, view: readonly MockRole[]): string | null {
  // D26G-3: клиент отклонил КП — решение менеджеру (роли с клиентами на полном доступе), как BFF
  if (row.state === "rejected" && row.rejectedBy === "client") {
    return full(view, "crm.clients") ? "Клиент отклонил КП по заявке" : null;
  }
  if (row.state === "not_started") return "Начать расчёт по заявке";
  if (row.state === "returned") return "Доработать расчёт по заявке";
  if (row.state !== "in_progress") return null;
  const mine = [
    ...(full(view, "erp.calc.goods") ? (["stock", "supply"] as const) : []),
    ...(full(view, "erp.calc.services") ? (["engineer"] as const) : []),
  ];
  if (mine.some((group) => row.visas[group] === "waiting")) {
    return "Завизировать строки расчёта по заявке";
  }
  const states = [row.visas.stock, row.visas.supply, row.visas.engineer];
  if (states.includes("done") && states.every((s) => s === "none" || s === "done")) {
    return "Отправить директору расчёт по заявке";
  }
  return "Рассчитать заявку";
}

function calcItems(view: readonly MockRole[]): QueueItem[] {
  const role = roleFor(view, "calc_task");
  const name = userName();
  if (!role || !name) return [];
  return myCalcRows(name).flatMap((row): QueueItem[] => {
    const action = calcAction(row, view);
    if (!action) return [];
    return [
      {
        id: `calc:${row.number}`,
        role_id: role.id,
        kind: "calc_task",
        title: `${action} ${row.number}`,
        subtitle: join(
          row.state === "rejected"
            ? row.rejectReason
              ? `Причина: ${row.rejectReason}`
              : "Причина не указана"
            : null,
          row.client,
          row.title,
          `по письму ${row.letter_number}`,
        ),
        due_label: dueLabel(row.due),
        due_at: new Date(`${row.due}T18:59:59Z`).toISOString(),
        object: {
          kind: "request",
          number: row.number,
          title: row.title,
          path: `/erp/calc/${seg(row.number)}`,
          step: "CALCULATION",
        },
      },
    ];
  });
}

// --- счета ------------------------------------------------------------------------------------

const invoiceRef = (card: PaymentCard): ObjectRef => ({
  kind: "invoice",
  number: card.number,
  title: card.client_name,
  path: `/eds/payments/${String(card.id)}?panel=open&tab=payment`,
});

function invoiceItems(view: readonly MockRole[]): QueueItem[] {
  const confirm = roleFor(view, "confirm_payment");
  const issue = roleFor(view, "issue_invoice");
  const items: QueueItem[] = [];
  for (const card of readInvoices()) {
    if (confirm && card.status === "proof_received" && card.has_pending_proof) {
      items.push({
        id: `invoice:${String(card.id)}:confirm`,
        role_id: confirm.id,
        kind: "confirm_payment",
        title: `Подтвердить оплату по счёту ${card.number}`,
        subtitle: join(
          card.client_name,
          money(card.balance.amount, card.balance.currency),
          card.project_number,
          "платёжка получена",
        ),
        due_label: "later",
        object: invoiceRef(card),
      });
    }
    if (issue && card.status === "draft") {
      items.push({
        id: `invoice:${String(card.id)}:issue`,
        role_id: issue.id,
        kind: "issue_invoice",
        title: `Выставить счёт ${card.number}`,
        subtitle: join(
          card.client_name,
          money(card.amount.amount, card.amount.currency),
          card.project_number,
        ),
        due_label: "later",
        object: invoiceRef(card),
      });
    }
  }
  return items;
}

// --- договор и акт ----------------------------------------------------------------------------

function contractStep(row: ProjectRow): [Kind, string, string] | null {
  const c = row.documents.contract;
  if (!c) {
    return row.problems.includes("no_contract")
      ? ["issue_contract", "Сформировать проект договора по", "КП принято клиентом"]
      : null;
  }
  if (c.status === "project" && !c.sent_to_client) {
    return [
      "issue_contract",
      `Отправить клиенту проект договора ${c.number} по`,
      "проект не отправлен",
    ];
  }
  if (c.status === "client_agreed") {
    return [
      "issue_contract",
      `Выставить у оператора договор ${c.number} по`,
      "клиент согласовал редакцию",
    ];
  }
  if (c.status === "issued_at_operator") {
    return [
      "attach_scan",
      `Прикрепить скан подписанного договора ${c.number} по`,
      "договор выставлен у оператора",
    ];
  }
  if (c.status === "rejected") {
    return ["issue_contract", `Доработать договор ${c.number} по`, "клиент отклонил"];
  }
  return null;
}

function actStep(row: ProjectRow): [string, string] | null {
  const { act, invoice } = row.documents;
  if (act?.status === "returned")
    return [`Выпустить заново акт ${act.number} по`, "заказчик вернул акт"];
  if (!act && row.client_status === "fulfilling" && invoice?.status === "paid") {
    return ["Выпустить акт по", "счета оплачены"];
  }
  return null;
}

function projectItems(view: readonly MockRole[]): QueueItem[] {
  const items: QueueItem[] = [];
  for (const row of readProjects().map(toRow)) {
    const path = (tab: "contract" | "act") =>
      `/eds/projects/${seg(row.number)}?panel=open&tab=${tab}`;
    if (row.step === "CONTRACT") {
      const step = contractStep(row);
      const role = step ? roleFor(view, step[0]) : undefined;
      if (step && role) {
        const c = row.documents.contract;
        items.push({
          id: `project:${row.number}:contract`,
          role_id: role.id,
          kind: step[0],
          title: `${step[1]} ${row.number}`,
          subtitle: join(row.client_name, row.title, step[2]),
          due_label: "later",
          object: {
            kind: c ? "contract" : "project",
            number: c ? c.number : row.number,
            title: row.client_name,
            path: path("contract"),
          },
        });
      }
    }
    const act = row.step === "PAYMENT" ? actStep(row) : null;
    const actRole = roleFor(view, "issue_act");
    if (act && actRole) {
      const a = row.documents.act;
      items.push({
        id: `project:${row.number}:act`,
        role_id: actRole.id,
        kind: "issue_act",
        title: `${act[0]} ${row.number}`,
        subtitle: join(row.client_name, row.title, act[1]),
        due_label: "later",
        object: {
          kind: a ? "act" : "project",
          number: a ? a.number : row.number,
          title: row.client_name,
          path: path("act"),
        },
      });
    }
  }
  return items;
}

/** Строки «Моих задач» из работы ERP для ролей «вида». */
export function erpWorkQueueItems(view: readonly MockRole[]): QueueItem[] {
  return [...calcItems(view), ...invoiceItems(view), ...projectItems(view)];
}

/** Бейджи «Мои расчёты» и «Счета и оплаты» — из тех же строк (как `build_counters` BFF). */
export function erpWorkCounters(view: readonly MockRole[]): MenuCounter[] {
  const items = erpWorkQueueItems(view);
  const out: MenuCounter[] = [];
  if (roleFor(view, "calc_task")) {
    const calc = items.filter((i) => i.kind === "calc_task").length;
    out.push({ module: "erp", section: "calc", count: calc, attention: calc > 0 });
  }
  if (roleFor(view, "confirm_payment") || roleFor(view, "issue_invoice")) {
    const pay = items.filter((i) => i.kind === "confirm_payment" || i.kind === "issue_invoice");
    out.push({ module: "eds", section: "payments", count: pay.length, attention: pay.length > 0 });
  }
  return out;
}

/** Карточки «Платёжки на подтверждение» и «Счета к выставлению» (как `build_cards` BFF). */
export function erpWorkCards(view: readonly MockRole[]): QueueCard[] {
  const items = erpWorkQueueItems(view);
  const cards: QueueCard[] = [];
  if (roleFor(view, "confirm_payment")) {
    cards.push({
      key: "payments_to_confirm",
      label: "Платёжки на подтверждение",
      count: items.filter((i) => i.kind === "confirm_payment").length,
      hint: "Документы · Счета и оплаты",
      path: "/eds/payments?show=proofs",
    });
  }
  if (roleFor(view, "issue_invoice")) {
    cards.push({
      key: "invoices_to_issue",
      label: "Счета к выставлению",
      count: items.filter((i) => i.kind === "issue_invoice").length,
      hint: "Документы · Счета и оплаты",
      path: "/eds/payments?show=to_issue",
    });
  }
  return cards;
}
