import { t } from "../../i18n/ru";

const ENQUEUE_FAILED = "handoff_enqueue_failed";

/** Код причины из `erp_handoff_error` → текст менеджеру (словарь подкодов API; свой код очереди). */
export function handoffErrorText(code: string | null | undefined): string {
  if (!code) return t.common.none;
  if (code === ENQUEUE_FAILED) return t.clients.handoffEnqueueFailed;
  return t.apiReasons[code] ?? code;
}
