import type { MenuCounter, QueueItem } from "../shared/api/generated/model";
import { QUEUE, allows } from "../app/rbac.generated";
import { readMemos, readQuotes } from "./fixtures/approvals";
import type { MockRole } from "./fixtures/roles";

/**
 * «Мои задачи»: решения по маршрутам EDS из тех же демо-складов, что экраны «КП на одобрение» и «На согласовании»
 * (как BFF `feeds/queue.py`): КП на моём шаге — «Одобрить КП-…» (D26G-4: источник — маршрут EDS, не ERP), служебка на
 * шаге «Бухгалтер» — «Принять к оплате» держателю права оплаты (`eds.payments` полный, D26G-9: и менеджеру-универсалу).
 * Одобрили КП или оплатили служебку на экране — строка ушла из очереди, карточки и бейджа (числа не задаются вручную).
 */
type Kind = QueueItem["kind"];

const seg = (value: string) => encodeURIComponent(value);
const NBSP = " ";
const join = (...parts: (string | null | undefined)[]) => parts.filter(Boolean).join(" · ");

function money(amount: string): string {
  const value = Number(amount);
  const shown = (Number.isInteger(value) ? String(value) : value.toFixed(2))
    .replace(".", ",")
    .replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return `${shown}${NBSP}сум`;
}

function roleFor(view: readonly MockRole[], kind: Kind): MockRole | undefined {
  const need = QUEUE[kind];
  return view.find((role) => allows(role.access, need.resource, need.level));
}

function quoteItems(view: readonly MockRole[]): QueueItem[] {
  const role = roleFor(view, "approve_quote");
  if (!role) return [];
  return readQuotes()
    .filter((q) => q.status === "open" && q.can_decide)
    .map((q) => ({
      id: `quote:${q.id}`,
      role_id: role.id,
      kind: "approve_quote" as const,
      title: `Одобрить ${q.number}`,
      subtitle: join(
        q.client_name,
        q.snapshot_total ? money(q.snapshot_total.amount) : null,
        q.request?.number,
      ),
      due_label: "later" as const,
      object: {
        kind: "quote" as const,
        number: q.number,
        ...(q.client_name ? { title: q.client_name } : {}),
        path: `/eds/drafts/${seg(q.number)}?panel=open&tab=approve`,
      },
    }));
}

function payMemoItems(view: readonly MockRole[]): QueueItem[] {
  const role = roleFor(view, "pay_memo");
  if (!role) return [];
  return readMemos()
    .filter(
      (m): m is typeof m & { number: string } =>
        m.number !== null &&
        m.status === "open" &&
        m.steps.some((s) => s.status === "current" && s.label === "Бухгалтер"),
    )
    .map((m) => ({
      id: `memo:${m.approval_id}`,
      role_id: role.id,
      kind: "pay_memo" as const,
      title: `Принять к оплате ${m.number} · ${m.subject}`,
      subtitle: "Бухгалтер",
      due_label: "memo" as const,
      object: {
        kind: "memo" as const,
        number: m.number,
        title: m.subject,
        path: `/eds/approvals/${seg(m.number)}?panel=open&tab=agree`,
      },
    }));
}

/** Строки «Моих задач» из маршрутов EDS для ролей «вида». */
export function edsDecisionQueueItems(view: readonly MockRole[]): QueueItem[] {
  return [...quoteItems(view), ...payMemoItems(view)];
}

/** Число «КП на одобрение» — те же строки, что в очереди (карточка и бейдж), `null` — вида работы у ролей нет. */
export function quotesToApprove(view: readonly MockRole[]): number | null {
  return roleFor(view, "approve_quote") ? quoteItems(view).length : null;
}

/** Бейдж «КП на одобрение» в подменю «Документы» (как `build_counters` BFF). */
export function quoteCounter(view: readonly MockRole[]): MenuCounter[] {
  const count = quotesToApprove(view);
  return count === null ? [] : [{ module: "eds", section: "drafts", count, attention: count > 0 }];
}
