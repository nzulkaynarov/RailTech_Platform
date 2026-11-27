import { HttpResponse, http } from "msw";

import type {
  IntegrationCard,
  IntegrationCardKey,
  IntegrationsOverview,
  StatusFact,
} from "../shared/api/generated/model";

/**
 * Сценарии для проверки правды о состоянии (НАСТ-П1): набор обзора «Сервисов» с заданными словами карточек и два сценария
 * сбоя CRM — «не отвечает» и «отвечает частично». Тесты подмешивают их через `server.use(...)`; экраны «Состояние»,
 * «Сервисы» и «Первый запуск» не вправе показать при них ни «Работает», ни «Всё в порядке», ни «Готово» для служб.
 */

const CARDS: readonly IntegrationCardKey[] = [
  "erp",
  "telegram",
  "mail",
  "services",
  "models",
  "spend",
  "storage",
  "system",
];

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

export const WORKS: StatusFact = {
  state: "works",
  checked_at: minutesAgo(3),
  source: "check",
  live: true,
};
export const UNKNOWN: StatusFact = {
  state: "unknown",
  checked_at: null,
  source: "none",
  live: false,
};

function card(key: IntegrationCardKey, fact: StatusFact): IntegrationCard {
  const works = fact.state === "works";
  return {
    key,
    fact,
    status: works
      ? "ok"
      : fact.state === "broken"
        ? "fail"
        : fact.state === "attention"
          ? "warn"
          : "unknown",
    access: "ok",
    note: works ? "all_ok" : fact.state === "unknown" ? "check_failed" : "no_data",
    count: null,
    amount_usd: null,
    last_activity_at: fact.checked_at,
  };
}

/** Обзор, в котором слова карточек заданы поимённо; остальные «Работает». */
export function overviewWith(
  facts: Partial<Record<IntegrationCardKey, StatusFact>> = {},
  attention: IntegrationsOverview["attention"] = [],
): IntegrationsOverview {
  return {
    checked_at: minutesAgo(1),
    cards: CARDS.map((key) => card(key, facts[key] ?? WORKS)),
    attention,
  };
}

const failure = (status: number) =>
  HttpResponse.json(
    { code: "BACKEND_UNAVAILABLE", message: "CRM не отвечает", source: "crm" },
    { status },
  );

/** CRM не отвечает вовсе: обзор, чек-лист мастера, шина и сводка — 503. */
export const crmDownHandlers = [
  http.get("*/admin/integrations", () => failure(503)),
  http.get("*/setup/checklist", () => failure(503)),
  http.get("*/admin/bus", () => failure(503)),
];

/**
 * CRM отвечает частично: обзор пришёл, но модели, хранилище и связь с расчётами не проверены, шина — «не удалось
 * проверить»; в «Требует внимания» — строки «Не удалось проверить» (так отвечает BFF, `check_failed`).
 */
export const crmPartialHandlers = [
  http.get("*/admin/integrations", () =>
    HttpResponse.json(
      overviewWith(
        { erp: UNKNOWN, models: UNKNOWN, storage: UNKNOWN, mail: { ...UNKNOWN, state: "stale" } },
        (["erp", "models", "storage"] as const).map((key) => ({
          id: `check:${key}`,
          card: key,
          severity: "warn" as const,
          kind: "check_failed" as const,
          subject: null,
          detail: null,
          group: null,
          technical: null,
        })),
      ),
    ),
  ),
  http.get("*/admin/bus", () => failure(503)),
];
