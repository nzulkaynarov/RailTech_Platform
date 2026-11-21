import { HttpResponse, http } from "msw";

import type { QueueItem, SigningApprovalRow } from "../shared/api/generated/model";
import { QUEUE, allows } from "../app/rbac.generated";
import type { MockRole } from "./fixtures/roles";
import { readSession } from "./mockSession";

/**
 * Подпись договора, счёта и акта (SIGN-4; BFF `GET /eds/signing-approvals`, СЦ-9: те же шаги — строки «Моих задач»
 * `sign_document`): демо-подписанту — директору — ждут договор и счёт. Подписал или отказал — шаг ушёл из списка и из
 * очереди. Состояние живёт в памяти страницы, как у соседних моков.
 */
const SIGNER = "u-demo-director";

interface Step extends SigningApprovalRow {
  signer: string;
}

const SEED: Step[] = [
  {
    id: "d1a00000-0000-4000-8000-000000000001",
    signer: SIGNER,
    kind: "contract",
    action: "sign",
    step: "Подписать",
    number: "CT-2026-014",
    title: "Договор поставки · ООО «Демо-Рейл»",
    amount: "125000000.00",
    currency: "UZS",
    created_at: "2026-11-20T09:30:00Z",
  },
  {
    id: "d1a00000-0000-4000-8000-000000000002",
    signer: SIGNER,
    kind: "invoice",
    action: "sign",
    step: "Подписать",
    number: "INV-2026-031",
    title: "Счёт на предоплату · ООО «Демо-Рейл»",
    amount: "37500000.00",
    currency: "UZS",
    created_at: "2026-11-20T11:10:00Z",
  },
];

let steps: Step[] = SEED.map((s) => ({ ...s }));

export function resetEdsSigningMock(): void {
  steps = SEED.map((s) => ({ ...s }));
}

const NOUN = { quote: "КП", contract: "договор", invoice: "счёт", act: "акт" } as const;
const NBSP = " ";

function mine(): Step[] {
  const userId = readSession()?.userId;
  return steps.filter((s) => s.signer === userId);
}

function money(amount: string, currency: string | null): string {
  const value = Number(amount);
  const shown = (Number.isInteger(value) ? String(value) : value.toFixed(2))
    .replace(".", ",")
    .replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return `${shown}${NBSP}${!currency || currency === "UZS" ? "сум" : currency}`;
}

/** Строки «Моих задач» `sign_document` по шагам подписи текущего сотрудника (виза — не подпись). */
export function signingQueueItems(view: readonly MockRole[]): QueueItem[] {
  const need = QUEUE["sign_document"];
  const role = view.find((r) => allows(r.access, need.resource, need.level));
  if (!role) return [];
  return mine()
    .filter((s) => s.action === "sign")
    .map((s) => ({
      id: `sign_document:${s.id}`,
      role_id: role.id,
      kind: "sign_document" as const,
      title: `Подписать ${NOUN[s.kind]} ${s.number}`,
      subtitle: [s.title, s.amount ? money(s.amount, s.currency) : null]
        .filter(Boolean)
        .join(" · "),
      due_label: "later" as const,
      object: {
        kind: s.kind,
        number: s.number,
        title: s.title,
        path: `/dashboard/queue?signing=${s.id}`,
      },
    }));
}

export const edsSigningHandlers = [
  http.get("*/eds/signing-approvals", () => {
    if (!readSession()) {
      return HttpResponse.json(
        { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
        { status: 401 },
      );
    }
    return HttpResponse.json({
      items: mine().map((step) => {
        const row: SigningApprovalRow = {
          id: step.id,
          kind: step.kind,
          action: step.action,
          step: step.step,
          number: step.number,
          title: step.title,
          amount: step.amount,
          currency: step.currency,
          created_at: step.created_at,
        };
        return row;
      }),
    });
  }),
  http.post("*/eds/signing-approvals/:id/decision", ({ params }) => {
    steps = steps.filter((s) => s.id !== params["id"]);
    return new HttpResponse(null, { status: 204 });
  }),
];
