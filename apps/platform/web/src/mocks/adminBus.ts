import { HttpResponse, http } from "msw";

import type {
  BusDelivery,
  BusDomain,
  BusDomainOverview,
  BusInboxEntry,
  BusJournal,
  BusRetryDeadIn,
  BusSources,
} from "../shared/api/generated/model";
import { failure, guard } from "./adminUsers";
import { BUS_NOW, type BusMock, readBus, subscriberView, writeBus } from "./fixtures/bus";

/**
 * Моки `/admin/bus*` (W13-A2, BFF 0.9.0): только раздел `admin` уровня `full` (директору — 403). Повторяют правила
 * домена: «Повторить» берёт `dead` и ожидающие (попытки с нуля), «Повторить все dead» — все `dead` подписчика, повтор
 * обработки — записи `failed` и `skipped`; повторять нечего — `retried: 0`. Курсор — смещение строкой (у BFF он
 * непрозрачный, SPA его не разбирает).
 */
const DOMAINS: readonly BusDomain[] = ["crm", "erp", "eds"];
const ALL_OK: BusSources = { crm: "ok", erp: "ok", eds: "ok" };

function isDomain(value: unknown): value is BusDomain {
  return typeof value === "string" && (DOMAINS as readonly string[]).includes(value);
}

function sourcesFor(domain: string | null): BusSources {
  if (!isDomain(domain)) return ALL_OK;
  return {
    crm: domain === "crm" ? "ok" : "not_applicable",
    erp: domain === "erp" ? "ok" : "not_applicable",
    eds: domain === "eds" ? "ok" : "not_applicable",
  };
}

function overview(state: BusMock, domain: BusDomain): BusDomainOverview {
  const subscribers = state.subscribers
    .filter((s) => s.domain === domain)
    .map((s) => subscriberView(state, s))
    .sort((a, b) => a.name.localeCompare(b.name));
  const inbox = state.inbox.filter((e) => e.domain === domain);
  const waiting = subscribers
    .filter((s) => s.enabled)
    .map((s) => s.oldest_undelivered_age_seconds)
    .filter((v): v is number => v !== null);
  return {
    domain,
    outbox_pending: state.outbox[domain],
    oldest_undelivered_age_seconds: waiting.length ? Math.max(...waiting) : null,
    dlq_size: subscribers.reduce((sum, s) => sum + s.dead, 0),
    inbox_received: inbox.filter((e) => e.status === "received").length,
    inbox_retrying: inbox.filter((e) => e.status === "received" && e.error !== null).length,
    inbox_failed: inbox.filter((e) => e.status === "failed").length,
    subscribers,
  };
}

function page<T>(rows: T[], url: URL): { items: T[]; next_cursor: string | null } {
  const offset = Number(url.searchParams.get("cursor") ?? "0") || 0;
  const limit = Number(url.searchParams.get("limit") ?? "50") || 50;
  const items = rows.slice(offset, offset + limit);
  const next = offset + limit < rows.length ? String(offset + limit) : null;
  return { items, next_cursor: next };
}

function matchesDelivery(d: BusDelivery, url: URL): boolean {
  const q = url.searchParams;
  const domain = q.get("domain");
  const status = q.get("status");
  const subscriber = q.get("subscriber");
  const type = q.get("type");
  const from = q.get("from");
  const to = q.get("to");
  return (
    (!domain || d.domain === domain) &&
    (!status || d.status === status) &&
    (!subscriber || d.subscriber === subscriber) &&
    (!type || d.event_type.includes(type)) &&
    (!from || d.created_at >= new Date(from).toISOString()) &&
    (!to || d.created_at < new Date(to).toISOString())
  );
}

function matchesInbox(e: BusInboxEntry, url: URL): boolean {
  const q = url.searchParams;
  const domain = q.get("domain");
  const errors = q.get("errors") === "true";
  const type = q.get("type");
  const failedOrRetrying = e.status === "failed" || (e.status === "received" && e.error !== null);
  return (
    (!domain || e.domain === domain) &&
    (!errors || failedOrRetrying) &&
    (!type || e.type.includes(type))
  );
}

function update(change: (state: BusMock) => number): number {
  const state = readBus();
  const count = change(state);
  writeBus(state);
  return count;
}

function requeue(d: BusDelivery): void {
  d.status = "pending";
  d.attempts = 0;
  d.next_attempt_at = BUS_NOW;
}

export const adminBusHandlers = [
  http.get("*/admin/bus", () => {
    const denied = guard("full");
    if (denied) return denied;
    const state = readBus();
    const body: BusJournal = { domains: DOMAINS.map((d) => overview(state, d)), sources: ALL_OK };
    return HttpResponse.json(body);
  }),

  http.get("*/admin/bus/deliveries", ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const url = new URL(request.url);
    const rows = readBus()
      .deliveries.filter((d) => matchesDelivery(d, url))
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    return HttpResponse.json({
      ...page(rows, url),
      sources: sourcesFor(url.searchParams.get("domain")),
    });
  }),

  http.get("*/admin/bus/inbox", ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const url = new URL(request.url);
    const rows = readBus()
      .inbox.filter((e) => matchesInbox(e, url))
      .sort((a, b) => b.received_at.localeCompare(a.received_at));
    return HttpResponse.json({
      ...page(rows, url),
      sources: sourcesFor(url.searchParams.get("domain")),
    });
  }),

  http.post("*/admin/bus/:domain/deliveries/retry-dead", async ({ params, request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as BusRetryDeadIn;
    if (!isDomain(params["domain"]) || !/^[a-z][a-z0-9-]{0,63}$/.test(body.subscriber)) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.");
    }
    const domain = params["domain"];
    const retried = update((state) => {
      const dead = state.deliveries.filter(
        (d) => d.domain === domain && d.subscriber === body.subscriber && d.status === "dead",
      );
      dead.forEach(requeue);
      return dead.length;
    });
    return HttpResponse.json({ retried });
  }),

  http.post("*/admin/bus/:domain/deliveries/:id/retry", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    if (!isDomain(params["domain"])) return failure(422, "VALIDATION_FAILED", "Проверьте поля.");
    const id = Number(params["id"]);
    const domain = params["domain"];
    const retried = update((state) => {
      const target = state.deliveries.find((d) => d.domain === domain && d.id === id);
      if (!target || (target.status !== "dead" && target.status !== "pending")) return 0;
      requeue(target);
      return 1;
    });
    return HttpResponse.json({ retried });
  }),

  http.post("*/admin/bus/:domain/inbox/:eventId/retry", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const domain = params["domain"];
    const eventId = params["eventId"];
    const retried = update((state) => {
      const target = state.inbox.find((e) => e.domain === domain && e.event_id === eventId);
      if (!target || (target.status !== "failed" && target.status !== "skipped")) return 0;
      // Обработчик исправлен: повтор проходит.
      target.status = "processed";
      target.error = null;
      target.attempts = 1;
      target.processed_at = BUS_NOW;
      return 1;
    });
    return HttpResponse.json({ retried });
  }),
];
