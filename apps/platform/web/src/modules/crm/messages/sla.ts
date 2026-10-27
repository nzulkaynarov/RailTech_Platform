import { useEffect, useState } from "react";

import type { HandoffInfo } from "../../../shared/api/generated/model";

/** Состояние таймера SLA передачи: сколько ждёт клиент и прошёл ли срок реакции. */
export interface SlaState {
  /** Минут с момента передачи (не меньше нуля) */
  minutes: number;
  /** Срок реакции прошёл — таймер красный, со словом «срок прошёл» */
  overdue: boolean;
}

export function slaState(
  handoff: Pick<HandoffInfo, "created_at" | "sla_due_at">,
  now: number,
): SlaState {
  const created = Date.parse(handoff.created_at);
  const minutes = Number.isNaN(created) ? 0 : Math.max(0, Math.floor((now - created) / 60_000));
  const due = handoff.sla_due_at ? Date.parse(handoff.sla_due_at) : Number.NaN;
  return { minutes, overdue: !Number.isNaN(due) && now > due };
}

/** Длительность словами по ключам `messages:duration.*`: «12 мин», «2 ч 5 мин», «1 д 3 ч». */
export function durationParts(minutes: number): { key: string; values: Record<string, number> } {
  if (minutes < 60) return { key: "minutes", values: { count: minutes } };
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return { key: "hours", values: { h: hours, m: minutes % 60 } };
  return { key: "days", values: { d: Math.floor(hours / 24), h: hours % 24 } };
}

/** Текущее время, обновляемое раз в `intervalMs` (таймер «ждёт N мин» идёт без перезапроса данных). */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, intervalMs);
    return () => {
      window.clearInterval(timer);
    };
  }, [intervalMs]);
  return now;
}

/** Ключ повтора ответа (`client_message_id`): один на черновик, тот же при «Повторить». */
export function newMessageKey(): string {
  const cryptoApi = globalThis.crypto as Crypto | undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") return cryptoApi.randomUUID();
  return `draft-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
