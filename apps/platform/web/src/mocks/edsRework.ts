import type { QueueItem } from "../shared/api/generated/model";
import { QUEUE, allows } from "../app/rbac.generated";
import { readEds } from "./fixtures/edsDocuments";
import type { MockRole } from "./fixtures/roles";
import { readSession } from "./mockSession";

/**
 * Строки «Доработать» «Моей очереди» (D1-6b, BFF 0.25.0) для MSW: документы сотрудника в статусе «Возвращён на доработку» из
 * того же хранилища, что «Мои документы» и «Продолжить» (`fixtures/edsDocuments`), — как их отдаёт EDS по токену автора
 * (`GET /documents?mine=true&status=returned`). Отправил документ снова — статус сменился, строка исчезла. Решение «Вернуть»
 * (кто и что написал) берётся из решений документа; строка ведёт в форму «Продолжить» (`/eds/new?draft=<id>`).
 */
const KINDS = ["memo", "application", "report"];
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

function companyDay(moment: number): number {
  return Math.floor((moment + 5 * HOUR) / (24 * HOUR));
}

function ago(then: number, now: number): string {
  const span = now - then;
  if (span < HOUR) return `${String(Math.max(1, Math.floor(span / MINUTE)))} мин назад`;
  if (span < 24 * HOUR) return `${String(Math.floor(span / HOUR))} ч назад`;
  const days = companyDay(now) - companyDay(then);
  return days <= 1 ? "вчера" : `${String(days)} дн. назад`;
}

function dueOf(dueDate: string | null, now: number): Pick<QueueItem, "due_label" | "due_at"> {
  if (!dueDate) return { due_label: "today" };
  const end = Date.parse(`${dueDate}T23:59:59+05:00`);
  const days = companyDay(end) - companyDay(now);
  const label = end < now ? "overdue" : days <= 0 ? "today" : days === 1 ? "tomorrow" : "later";
  return { due_label: label, due_at: new Date(end).toISOString() };
}

/** Строки «Доработать» для сотрудника сессии и ролей «вида» (раздел `eds.memo.create` уровня `full` — автор документов). */
export function reworkQueueItems(view: readonly MockRole[], now = Date.now()): QueueItem[] {
  const session = readSession();
  const role = view.find((r) => allows(r.access, QUEUE.rework_document.resource, "full"));
  if (!session || !role) return [];
  return readEds()
    .documents.filter(
      (doc) =>
        doc.ownerId === session.userId && doc.status === "returned" && KINDS.includes(doc.kind),
    )
    .map((doc): QueueItem => {
      const decision = [...doc.decisions].reverse().find((d) => d.decision === "return");
      const remark = decision?.comment
        ? `Вернул ${decision.by.full_name}: ${decision.comment}`
        : decision
          ? `Вернул ${decision.by.full_name}`
          : "Возвращён на доработку";
      const number = doc.number ?? doc.subject;
      return {
        id: `rework:${doc.id}`,
        role_id: role.id,
        kind: "rework_document",
        title: `Доработать: ${number}${number === doc.subject ? "" : ` · ${doc.subject}`}`,
        subtitle: decision ? `${remark} · ${ago(Date.parse(decision.at), now)}` : remark,
        ...dueOf(doc.due_date, now),
        object: {
          kind: "memo",
          number,
          title: doc.subject,
          path: `/eds/new?draft=${doc.id}`,
        },
      };
    });
}
