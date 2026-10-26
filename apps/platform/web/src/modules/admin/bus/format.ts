import { useQueryClient } from "@tanstack/react-query";
import type { TFunction } from "i18next";

import { ApiError } from "../../../shared/api/errors";
import type {
  BusDelivery,
  BusDomain,
  BusInboxEntry,
  BusSourceState,
  BusSources,
  BusSubscriberState,
} from "../../../shared/api/generated/model";
import type { StatusTone } from "../../../shared/lib/statuses";

/** Домены журнала в порядке экрана (как в ответе BFF). */
export const DOMAINS: readonly BusDomain[] = ["crm", "erp", "eds"];

/** Ключ строки доставки: id уникален только внутри домена. */
export function deliveryKey(delivery: Pick<BusDelivery, "domain" | "id">): string {
  return `${delivery.domain}:${String(delivery.id)}`;
}

export function inboxKey(entry: Pick<BusInboxEntry, "domain" | "event_id">): string {
  return `${entry.domain}:${entry.event_id}`;
}

/** Тип события без общего префикса и версии: `uz.railtech.erp.quote.sent.v1` → `erp.quote.sent`. */
export function shortType(type: string): string {
  return type.replace(/^uz\.railtech\./, "").replace(/\.v\d+$/, "");
}

/** Имя подписчика для людей: известные сервисы ансамбля — словами, остальные — как в файле подписок. */
const KNOWN_SUBSCRIBERS = ["crm", "erp", "eds", "platform-bff"] as const;

export function subscriberName(t: TFunction, name: string): string {
  return (KNOWN_SUBSCRIBERS as readonly string[]).includes(name)
    ? t(`bus:subscriberNames.${name}`)
    : name;
}

export function domainName(t: TFunction, domain: BusDomain): string {
  return t(`bus:domains.${domain}`);
}

/** Состояние подписчика → цвет тега; слово есть всегда (SPEC-v3 §5.2). */
export const STATE_TONE: Record<BusSubscriberState, StatusTone> = {
  ok: "green",
  failing: "gold",
  paused: "red",
  dead_letters: "red",
  disabled: "default",
  removed: "default",
};

export type DeliveryWord = "pending" | "retrying" | "in_flight" | "delivered" | "dead";

/** Ждущая доставка после неудачной попытки — «Ждёт повтора», а не «Ждёт отправки». */
export function deliveryWord(delivery: BusDelivery): DeliveryWord {
  if (delivery.status === "pending" && delivery.attempts > 0) return "retrying";
  return delivery.status;
}

export const DELIVERY_TONE: Record<DeliveryWord, StatusTone> = {
  pending: "blue",
  retrying: "gold",
  in_flight: "blue",
  delivered: "green",
  dead: "red",
};

export type InboxWord = "received" | "retrying" | "processed" | "failed" | "skipped";

export function inboxWord(entry: BusInboxEntry): InboxWord {
  if (entry.status === "received" && entry.error) return "retrying";
  return entry.status;
}

export const INBOX_TONE: Record<InboxWord, StatusTone> = {
  received: "blue",
  retrying: "gold",
  processed: "green",
  failed: "red",
  skipped: "default",
};

/** Возраст «самого старого недоставленного» словами: секунды, минуты, часы, дни. */
export function ageText(t: TFunction, seconds: number | null): string | null {
  if (seconds === null) return null;
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return t("bus:age.seconds", { count: s });
  if (s < 3600) return t("bus:age.minutes", { count: Math.floor(s / 60) });
  if (s < 86400) return t("bus:age.hours", { count: Math.floor(s / 3600) });
  return t("bus:age.days", { count: Math.floor(s / 86400) });
}

/** Домены, о которых стоит сказать плашкой: не ответил, отказал; «нет доступа» — только если домен в фильтре. */
export function troubledSources(
  sources: BusSources | undefined,
): { domain: BusDomain; state: Exclude<BusSourceState, "ok"> }[] {
  if (!sources) return [];
  return DOMAINS.flatMap((domain) => {
    const state = sources[domain];
    return state === "unavailable" || state === "forbidden" ? [{ domain, state }] : [];
  });
}

/** Сброс кэша журнала после повтора: сводка, доставки и inbox перечитываются. */
export function useRefreshBus(): () => void {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      predicate: (query) => String(query.queryKey[0]).startsWith("/api/v1/admin/bus"),
    });
  };
}

const CODES = ["FORBIDDEN", "BACKEND_UNAVAILABLE", "VALIDATION_FAILED"] as const;

/** Ошибка действия журнала словами; источник (домен) — в тексте плашки над таблицей, здесь только суть. */
export function busErrorText(t: TFunction, error: unknown): string {
  if (error instanceof ApiError && (CODES as readonly string[]).includes(error.code)) {
    return t(`bus:errors.${error.code}`);
  }
  return t("bus:errors.DEFAULT");
}
