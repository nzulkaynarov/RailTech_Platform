import type { ClientDetail } from "../../api/generated/model";
import { t } from "../../i18n/ru";

const ENQUEUE_FAILED = "handoff_enqueue_failed";

/** Код причины из `erp_handoff_error` → текст менеджеру (словарь подкодов API; свой код очереди). */
export function handoffErrorText(code: string | null | undefined): string {
  if (!code) return t.common.none;
  if (code === ENQUEUE_FAILED) return t.clients.handoffEnqueueFailed;
  return t.apiReasons[code] ?? code;
}

/**
 * Лид, из которого идёт повторная передача (тот же вызов, что «Передать в бэк-офис»): в стадии
 * «клиент» (его и передавали), иначе последний по номеру.
 */
export function retryLeadId(client: ClientDetail): number | null {
  const pick = (leads: ClientDetail["leads"]) =>
    leads.reduce<number | null>(
      (max, lead) => (max === null || lead.id > max ? lead.id : max),
      null,
    );
  const customers = client.leads.filter((lead) => lead.stage === "customer");
  return pick(customers.length > 0 ? customers : client.leads);
}
