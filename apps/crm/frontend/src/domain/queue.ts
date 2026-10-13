import type { InboxResponse } from "../api/generated/model";
import { sortHandoffs } from "./sla";

/** Место лида в очереди «Входящих» и соседи для переходов «предыдущий / следующий». */
export type QueuePosition = {
  index: number;
  total: number;
  prevId: number | null;
  nextId: number | null;
};

type Inbox = Pick<InboxResponse, "escalations" | "mine" | "unassigned">;

/**
 * Порядок очереди — как на экране «Входящие»: передачи (горячие и дольше ждущие первыми),
 * затем мои лиды, затем без ответственного; лид считается один раз.
 * Бенчмарк: Front/Intercom «next conversation» — менеджер проходит очередь, не возвращаясь в список.
 */
export function inboxQueue(inbox: Inbox): number[] {
  const seen = new Set<number>();
  const ids: number[] = [];
  for (const lead of [...sortHandoffs(inbox.escalations), ...inbox.mine, ...inbox.unassigned]) {
    if (seen.has(lead.id)) continue;
    seen.add(lead.id);
    ids.push(lead.id);
  }
  return ids;
}

/** `null`, если лида нет в очереди (закрыт, вернулся боту или открыт не из входящих). */
export function queuePosition(ids: readonly number[], leadId: number): QueuePosition | null {
  const index = ids.indexOf(leadId);
  if (index < 0) return null;
  return {
    index,
    total: ids.length,
    prevId: ids[index - 1] ?? null,
    nextId: ids[index + 1] ?? null,
  };
}

export type QueueKey = {
  /** `KeyboardEvent.code` — не зависит от раскладки (ru/uz/en). */
  code: string;
  altKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  /** Фокус в поле ввода — буквы принадлежат тексту. */
  inField: boolean;
};

/** J — следующий, K — предыдущий (Gmail, Linear, Front); без модификаторов и вне полей ввода. */
export function queueKeyAction(key: QueueKey): "next" | "prev" | null {
  if (key.inField || key.altKey || key.ctrlKey || key.metaKey) return null;
  if (key.code === "KeyJ") return "next";
  if (key.code === "KeyK") return "prev";
  return null;
}

/** Фокус в элементе, куда печатают: input, textarea, select или contenteditable. */
export function isTextTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}
