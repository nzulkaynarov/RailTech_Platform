import { HttpResponse, http } from "msw";

import type {
  AiModel,
  AiModelChange,
  AiModelChangeIn,
  AttentionItem,
  BotProfile,
  ErpPairIn,
  ExternalService,
  IntegrationCard,
  IntegrationCardKey,
  IntegrationNote,
  IntegrationStatus,
  IntegrationsOverview,
  PasswordConfirm,
  ProviderKeyIn,
  ServiceState,
  ServiceSwitchIn,
  SmtpSettingsIn,
  TelegramTokenIn,
} from "../shared/api/generated/model";
import { failure, guard } from "./adminUsers";
import {
  MOCK_NOW,
  type IntegrationsMock,
  aiSpendReport,
  readIntegrations,
  spendReport,
  writeIntegrations,
} from "./fixtures/integrations";
import { groupsOf, settleOk, withState } from "./fixtures/integrationsHealth";
import { DEMO_WRONG_PASSWORD } from "./fixtures/users";
import { markStepDone } from "./setupState";

/**
 * Моки `/admin/integrations*` (W13-A1, BFF 0.7.0): раздел `admin` — чтение от `read`, изменения и пробы только `full`.
 * Повторяют правила CRM: неверный пароль — 422 `WRONG_PASSWORD`, поле не принято — 422 `VALIDATION_FAILED` с подкодом
 * в `details.reason`, проба не прошла — 502 `INTEGRATION_FAILED`. Значений секретов в состоянии и ответах нет.
 * Связи действий: «Проверить» у почты восстанавливает сервис, смена ключа модели чинит её поставщика.
 */
const last4 = (secret: string) => secret.slice(-4);

function wrongPassword(password: string) {
  return password === DEMO_WRONG_PASSWORD
    ? failure(422, "WRONG_PASSWORD", "Пароль указан неверно.", "crm", {
        fields: ["password"],
        reason: "wrong_password",
      })
    : null;
}

function invalid(field: string, reason: string) {
  return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "crm", {
    fields: [field],
    reason,
  });
}

const MOCK_PROVIDERS = ["anthropic", "gemini", "openai"];

/** Как CRM (`models_admin.normalize_model`): префикс выбранного провайдера снимается, чужой префикс и мусор — 422 по полю. */
function normalizeModel(provider: string, raw: string): string | null {
  let name = raw.trim();
  const head = name.split("/")[0] ?? "";
  if (name.includes("/") && head.toLowerCase() === provider) name = name.slice(head.length + 1);
  const next = name.split("/")[0] ?? "";
  if (name.includes("/") && MOCK_PROVIDERS.includes(next.toLowerCase())) return null;
  return /^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$/.test(name) ? name : null;
}

function probeFailed(reason: string) {
  return failure(502, "INTEGRATION_FAILED", "Проверка не прошла.", "crm", { reason });
}

function update(change: (state: IntegrationsMock) => void): IntegrationsMock {
  const state = readIntegrations();
  change(state);
  writeIntegrations(state);
  return state;
}

// --- Свод: те же правила, что в BFF (`integrations_overview.py`), в упрощённом виде ---------------------

const RANK: Record<IntegrationStatus, number> = { ok: 0, unknown: 1, warn: 2, fail: 3, off: -1 };

function worst(levels: IntegrationStatus[]): IntegrationStatus {
  const active = levels.filter((level) => level !== "off");
  if (active.length === 0) return "off";
  return active.reduce((a, b) => (RANK[b] > RANK[a] ? b : a));
}

function lastOf(...values: (string | null | undefined)[]): string | null {
  const present = values.filter((v): v is string => Boolean(v));
  return present.length ? present.reduce((a, b) => (a > b ? a : b)) : null;
}

/** Уровень сервиса для карточек: «ожидаемо на стенде» и «не настроено» — не сбой (как в BFF). */
function levelOf(s: ExternalService): IntegrationStatus {
  return s.state === "expected" || s.state === "not_configured" ? "off" : s.status;
}

function overview(state: IntegrationsMock): IntegrationsOverview {
  const services = state.services.map(withState);
  const by = (keys: (key: string) => boolean) => services.filter((s) => keys(s.key));
  const problems = (list: ExternalService[]) =>
    list.filter((s) => s.state === "broken" || s.state === "degraded");
  const groups = groupsOf(services, state.models, MOCK_NOW);
  const covered = new Set(
    groups.filter((g) => g.state !== "not_checked").flatMap((g) => g.service_keys),
  );
  const card = (
    key: IntegrationCardKey,
    status: IntegrationStatus,
    note: IntegrationNote,
    count: number | null = null,
    last: string | null = null,
    amount: number | null = null,
  ): IntegrationCard => ({
    key,
    status,
    access: "ok",
    note,
    count,
    amount_usd: amount,
    last_activity_at: last,
  });

  const erpServices = by((k) => ["erp_sync", "erp_handoff", "erp_events"].includes(k));
  const telegram = services.find((s) => s.key === "telegram");
  const mail = services.find((s) => s.key === "mail");
  const modelServices = by((k) => k === "litellm" || k.startsWith("vendor."));
  const storageServices = by((k) => k === "s3" || k === "backup");

  const erpCard = !state.erp.configured
    ? card("erp", "off", "not_configured")
    : card(
        "erp",
        worst(erpServices.map(levelOf)),
        problems(erpServices).length
          ? "problems"
          : state.erp.rotation_pending
            ? "rotation_pending"
            : "all_ok",
        problems(erpServices).length || null,
        lastOf(state.erp.token_updated_at, ...erpServices.map((s) => s.checked_at)),
      );
  const tgCard = !state.telegram.configured
    ? card("telegram", "off", "not_configured")
    : telegram?.switch?.disabled
      ? card("telegram", telegram.status, "paused", null, telegram.checked_at)
      : telegram && (telegram.state === "broken" || telegram.state === "degraded")
        ? card("telegram", telegram.status, "problems", 1, telegram.checked_at)
        : card("telegram", telegram?.status ?? "unknown", "all_ok", null, telegram?.checked_at);
  const mailCard = !state.smtp.configured
    ? card("mail", "off", "not_configured")
    : mail?.switch?.disabled
      ? card("mail", mail.status, "paused", null, mail.checked_at)
      : mail && (mail.state === "broken" || mail.state === "degraded")
        ? card("mail", mail.status, "problems", 1, mail.checked_at)
        : card("mail", mail?.status ?? "unknown", "all_ok", null, mail?.checked_at);
  const brokenModels = state.models.filter(
    (m) => m.health === "problem" && !covered.has(`vendor.${m.provider ?? ""}`),
  );
  const modelLevels: IntegrationStatus[] = [
    ...modelServices.map(levelOf),
    ...state.models
      .filter((m) => !covered.has(`vendor.${m.provider ?? ""}`))
      .map((m): IntegrationStatus =>
        m.health === "problem" ? "fail" : m.health === "ok" ? "ok" : "unknown",
      ),
  ];
  const modelCount = brokenModels.length + problems(modelServices).length;
  const modelsCard = card(
    "models",
    worst(modelLevels),
    modelCount ? "problems" : "all_ok",
    modelCount || null,
    lastOf(...modelServices.map((s) => s.checked_at), ...state.models.map((m) => m.checked_at)),
  );
  const servicesProblems = problems(services);
  const servicesCard = card(
    "services",
    worst(services.map(levelOf)),
    servicesProblems.length ? "problems" : "all_ok",
    servicesProblems.length || null,
    lastOf(...services.map((s) => s.checked_at)),
  );
  const report = spendReport(7);
  const ratio = Math.max(
    ...report.providers.map((p) => (p.limit_usd > 0 ? p.spent_usd / p.limit_usd : 0)),
  );
  const spendCard = card(
    "spend",
    ratio >= 1 ? "fail" : ratio >= 0.8 ? "warn" : "ok",
    ratio >= 1 ? "budget_over" : ratio >= 0.8 ? "budget_near" : "all_ok",
    null,
    null,
    report.today_usd,
  );
  const b = state.backups;
  const storageStale = b.stale || b.last_success_at === null || !b.available;
  const storageCard = card(
    "storage",
    worst([...storageServices.map(levelOf), storageStale ? "warn" : "ok"]),
    b.last_success_at === null
      ? "no_backups"
      : b.stale
        ? "backup_stale"
        : problems(storageServices).length
          ? "problems"
          : "all_ok",
    problems(storageServices).length || null,
    lastOf(b.last_success_at, ...storageServices.map((s) => s.checked_at)),
  );
  const badComponents = state.components.filter((c) => c.status === "warn" || c.status === "fail");
  const systemCard = card(
    "system",
    worst(state.components.map((c) => c.status)),
    badComponents.length ? "problems" : "all_ok",
    badComponents.length || null,
    lastOf(...state.components.map((c) => c.checked_at)),
  );

  const attention: AttentionItem[] = [];
  const push = (item: AttentionItem) => attention.push(item);
  const severityOf: Partial<Record<ServiceState, AttentionItem["severity"]>> = {
    broken: "fail",
    degraded: "warn",
    not_configured: "setup",
    not_checked: "warn",
  };
  for (const g of groups) {
    const severity = severityOf[g.state];
    if (severity === undefined || (g.state === "not_checked" && g.owner !== "hosting")) continue;
    push({
      id: `group:${g.id}`,
      card: g.fix_card ?? "services",
      severity,
      kind: "service",
      subject: g.headline,
      detail: g.detail,
      group: g,
      technical: null,
    });
  }
  for (const s of services) {
    if (s.switch?.disabled) {
      push({
        id: `paused:${s.key}`,
        card: s.fix_card ?? "services",
        severity: "warn",
        kind: "paused",
        subject: s.title,
        detail: s.switch.reason,
        group: null,
        technical: null,
      });
    }
  }
  if (!state.erp.configured)
    push({
      id: "setup:erp",
      card: "erp",
      severity: "setup",
      kind: "not_configured",
      subject: null,
      detail: null,
      group: null,
      technical: null,
    });
  else if (state.erp.rotation_pending)
    push({
      id: "rotation:erp",
      card: "erp",
      severity: "warn",
      kind: "rotation_pending",
      subject: null,
      detail: null,
      group: null,
      technical: null,
    });
  if (!state.telegram.configured)
    push({
      id: "setup:telegram",
      card: "telegram",
      severity: "setup",
      kind: "not_configured",
      subject: null,
      detail: null,
      group: null,
      technical: null,
    });
  if (!state.smtp.configured)
    push({
      id: "setup:mail",
      card: "mail",
      severity: "setup",
      kind: "not_configured",
      subject: null,
      detail: null,
      group: null,
      technical: null,
    });
  for (const m of brokenModels) {
    push({
      id: `model:${m.alias}`,
      card: "models",
      severity: "fail",
      kind: "model_problem",
      subject: m.alias,
      detail: null,
      group: null,
      technical: m.health_detail,
    });
  }
  if (storageStale)
    push({
      id: "backup:stale",
      card: "storage",
      severity: "warn",
      kind: "backup_stale",
      subject: null,
      detail: null,
      group: null,
      technical: null,
    });
  for (const c of badComponents) {
    push({
      id: `component:${c.key}`,
      card: "system",
      severity: c.status === "fail" ? "fail" : "warn",
      kind: "component",
      subject: c.title,
      detail: c.reason,
      group: null,
      technical: null,
    });
  }
  const order = { fail: 0, warn: 1, setup: 2 } as const;
  attention.sort((a, c) => order[a.severity] - order[c.severity]);
  return {
    checked_at: MOCK_NOW,
    cards: [
      erpCard,
      tgCard,
      mailCard,
      servicesCard,
      modelsCard,
      spendCard,
      storageCard,
      systemCard,
    ],
    attention,
  };
}

// --- Обработчики -------------------------------------------------------------------------------------

function findService(state: IntegrationsMock, key: string) {
  return state.services.find((s) => s.key === key);
}

function detail(service: ExternalService) {
  return {
    service,
    checks: service.checked_at
      ? [
          {
            checked_at: service.checked_at,
            tier: "manual" as const,
            status: service.status,
            latency_ms: service.latency_ms,
            summary: service.summary,
            error: service.error,
          },
        ]
      : [],
    days: [{ day: "2026-10-25", ok: 1400, warn: 20, fail: 1, unknown: 0, uptime: 0.998 }],
    incidents: service.incident ? [service.incident] : [],
  };
}

export const adminIntegrationsHandlers = [
  http.get("*/admin/integrations", () => {
    const denied = guard("read");
    if (denied) return denied;
    return HttpResponse.json(overview(readIntegrations()));
  }),

  // --- ERP
  http.get(
    "*/admin/integrations/erp",
    () => guard("read") ?? HttpResponse.json(readIntegrations().erp),
  ),
  http.post("*/admin/integrations/erp/check", () => {
    const denied = guard("full");
    if (denied) return denied;
    if (!readIntegrations().erp.configured) {
      return failure(409, "NOT_CONFIGURED", "Подключение ещё не настроено.", "crm", {
        reason: "erp_not_configured",
      });
    }
    return HttpResponse.json({
      status: "ok",
      checked_at: MOCK_NOW,
      latency_ms: 42,
      version: "1.9.0",
      migrations_applied: true,
      queue_alive: true,
      retry_after_s: null,
    });
  }),
  http.post("*/admin/integrations/erp/pair", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as ErpPairIn;
    const wrong = wrongPassword(body.password);
    if (wrong) return wrong;
    if (!/^https?:\/\//.test(body.base_url)) return invalid("base_url", "erp_invalid_url");
    if (body.code === "000000") return invalid("code", "erp_pairing_code_invalid");
    const state = update((s) => {
      s.erp = {
        ...s.erp,
        base_url: body.base_url,
        configured: true,
        paired: true,
        rotation_pending: false,
        token_configured: true,
        token_last4: "5a1d",
        webhook_secret_configured: true,
        webhook_secret_last4: "c0de",
        token_updated_at: MOCK_NOW,
      };
    });
    markStepDone("erp"); // чистая установка: шаг первого запуска «ERP» сделан
    return HttpResponse.json({
      status: state.erp,
      check: {
        status: "ok",
        checked_at: MOCK_NOW,
        latency_ms: 38,
        version: "1.9.0",
        migrations_applied: true,
        queue_alive: true,
        retry_after_s: null,
      },
      check_error: null,
    });
  }),
  http.post("*/admin/integrations/erp/rotate", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as PasswordConfirm;
    const wrong = wrongPassword(body.password);
    if (wrong) return wrong;
    if (!readIntegrations().erp.configured) {
      return failure(409, "NOT_CONFIGURED", "Подключение ещё не настроено.", "crm", {
        reason: "erp_not_configured",
      });
    }
    const state = update((s) => {
      s.erp = {
        ...s.erp,
        rotation_pending: true,
        previous_secret_until: "2026-10-27T09:12:00Z",
        token_last4: "e7b2",
        token_updated_at: MOCK_NOW,
      };
    });
    return HttpResponse.json({
      status: state.erp,
      check: {
        status: "ok",
        checked_at: MOCK_NOW,
        latency_ms: 40,
        version: "1.9.0",
        migrations_applied: true,
        queue_alive: true,
        retry_after_s: null,
      },
      check_error: null,
    });
  }),

  // --- Telegram
  http.get(
    "*/admin/integrations/telegram",
    () => guard("read") ?? HttpResponse.json(readIntegrations().telegram),
  ),
  http.put("*/admin/integrations/telegram/token", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as TelegramTokenIn;
    const wrong = wrongPassword(body.password);
    if (wrong) return wrong;
    if (body.token.startsWith("bad-")) return invalid("token", "invalid_bot_token");
    const state = update((s) => {
      s.telegram = {
        ...s.telegram,
        configured: true,
        last4: last4(body.token),
        updated_at: MOCK_NOW,
        running: true,
        last_error: null,
      };
    });
    markStepDone("bot"); // как BFF: шаг «Telegram-бот» сделан, когда токен задан (W15-H4)
    return HttpResponse.json(state.telegram);
  }),
  http.get("*/admin/integrations/telegram/channels", () => {
    const denied = guard("read");
    if (denied) return denied;
    return HttpResponse.json({ items: readIntegrations().channels });
  }),
  http.post("*/admin/integrations/telegram/channels/:chatId/connect", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const id = Number(params["chatId"]);
    update((s) => {
      const channel = s.channels.find((c) => c.chat_id === id);
      if (channel) s.telegram = { ...s.telegram, channel_id: id, channel_title: channel.title };
    });
    return HttpResponse.json({ ok: true, id: null });
  }),
  http.post("*/admin/integrations/telegram/channel/test", () => {
    const denied = guard("full");
    if (denied) return denied;
    if (readIntegrations().telegram.channel_id === null) {
      return failure(409, "NOT_CONFIGURED", "Подключение ещё не настроено.", "crm", {
        reason: "channel_not_configured",
      });
    }
    return HttpResponse.json({ ok: true, id: null });
  }),
  http.get("*/admin/integrations/telegram/profile", () => {
    const denied = guard("read");
    if (denied) return denied;
    const state = readIntegrations();
    return HttpResponse.json({ profile: state.profile, published: state.published });
  }),
  http.put("*/admin/integrations/telegram/profile", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as BotProfile;
    const state = update((s) => {
      s.profile = body;
      s.published = { ok: true, at: MOCK_NOW, changed: 3, error: null, retry_after: null };
    });
    return HttpResponse.json({ profile: state.profile, published: state.published });
  }),

  // --- Почта
  http.get(
    "*/admin/integrations/smtp",
    () => guard("read") ?? HttpResponse.json(readIntegrations().smtp),
  ),
  http.put("*/admin/integrations/smtp", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as SmtpSettingsIn;
    const wrong = wrongPassword(body.password);
    if (wrong) return wrong;
    if (/\s/.test(body.host)) return invalid("host", "smtp_invalid_host");
    const state = update((s) => {
      s.smtp = {
        ...s.smtp,
        configured: body.host.trim() !== "",
        host: body.host,
        port: body.port ?? 587,
        security: body.security ?? "starttls",
        from_email: body.from_email ?? "",
        from_name: body.from_name ?? "",
        username: body.username ?? s.smtp.username,
        ...(body.smtp_password
          ? {
              password_configured: true,
              password_last4: last4(body.smtp_password),
              password_updated_at: MOCK_NOW,
            }
          : {}),
      };
    });
    if (state.smtp.configured) markStepDone("mail"); // шаг «Почта» (W15-H4)
    return HttpResponse.json(state.smtp);
  }),
  http.post("*/admin/integrations/smtp/check", () => {
    const denied = guard("full");
    if (denied) return denied;
    const smtp = readIntegrations().smtp;
    if (!smtp.configured) {
      return failure(409, "NOT_CONFIGURED", "Подключение ещё не настроено.", "crm", {
        reason: "smtp_not_configured",
      });
    }
    if (smtp.host.includes("bad")) return probeFailed("smtp_auth_failed");
    update((s) => {
      const mail = findService(s, "mail");
      if (mail) settleOk(mail, MOCK_NOW, "Соединение и вход в порядке");
    });
    return HttpResponse.json({ server: `${smtp.host} ESMTP`, authenticated: true, latency_ms: 85 });
  }),
  http.post("*/admin/integrations/smtp/test-send", () => {
    const denied = guard("full");
    if (denied) return denied;
    if (!readIntegrations().smtp.configured) {
      return failure(409, "NOT_CONFIGURED", "Подключение ещё не настроено.", "crm", {
        reason: "smtp_not_configured",
      });
    }
    const state = update((s) => {
      s.mailLog.unshift({
        id: Math.max(0, ...s.mailLog.map((r) => r.id)) + 1,
        to_email: "admin@demo.example",
        subject: "Тестовое письмо",
        template: "test",
        purpose: "test",
        source: "crm",
        attachments: 0,
        status: "sent",
        error: null,
        attempts: 1,
        created_at: MOCK_NOW,
        sent_at: MOCK_NOW,
      });
    });
    return HttpResponse.json({
      email_log_id: state.mailLog[0]?.id ?? 0,
      to_email: "admin@demo.example",
      status: "queued",
    });
  }),
  http.get("*/admin/integrations/smtp/log", ({ request }) => {
    const denied = guard("read");
    if (denied) return denied;
    const url = new URL(request.url);
    const status = url.searchParams.get("status");
    const limit = Number(url.searchParams.get("limit") ?? 50);
    const items = readIntegrations()
      .mailLog.filter((row) => !status || row.status === status)
      .slice(0, limit);
    return HttpResponse.json({ items });
  }),

  // --- Внешние сервисы
  http.get("*/admin/integrations/services", () => {
    const denied = guard("read");
    if (denied) return denied;
    const state = readIntegrations();
    const items = state.services.map(withState);
    const summary = { ok: 0, warn: 0, fail: 0, unknown: 0, off: 0, disabled: 0 };
    for (const s of items) {
      summary[levelOf(s) === "off" || s.state === "disabled" ? "off" : s.status] += 1;
      if (s.switch?.disabled) summary.disabled += 1;
    }
    return HttpResponse.json({
      checked_at: MOCK_NOW,
      summary,
      items,
      stand: true,
      groups: groupsOf(items, state.models, MOCK_NOW),
    });
  }),
  http.get("*/admin/integrations/services/:key", ({ params }) => {
    const denied = guard("read");
    if (denied) return denied;
    const service = findService(readIntegrations(), String(params["key"]));
    return service
      ? HttpResponse.json(detail(service))
      : failure(404, "NOT_FOUND", "Не найдено.", "crm");
  }),
  http.post("*/admin/integrations/services/:key/check", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const key = String(params["key"]);
    let result: ExternalService | undefined;
    update((s) => {
      const service = findService(s, key);
      if (!service) return;
      if (service.status !== "off") service.checked_at = MOCK_NOW;
      if (key === "mail") settleOk(service, MOCK_NOW, "Очередь писем разобрана");
      result = service;
    });
    return result
      ? HttpResponse.json(detail(result))
      : failure(404, "NOT_FOUND", "Не найдено.", "crm");
  }),
  http.post("*/admin/integrations/services/:key/disable", async ({ request, params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as ServiceSwitchIn;
    const wrong = wrongPassword(body.password);
    if (wrong) return wrong;
    const key = String(params["key"]);
    const current = findService(readIntegrations(), key);
    if (!current) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    const toggle = current.switch;
    if (!toggle) {
      return failure(409, "SERVICE_NOT_SWITCHABLE", "У этого сервиса нет выключателя.", "crm", {
        reason: "service_not_switchable",
      });
    }
    const state = update((s) => {
      const service = findService(s, key);
      if (service) {
        service.switch = {
          ...toggle,
          disabled: true,
          reason: body.reason ?? null,
          changed_at: MOCK_NOW,
          changed_by: "Демо Админов",
        };
      }
    });
    return HttpResponse.json(findService(state, key));
  }),
  http.post("*/admin/integrations/services/:key/enable", async ({ request, params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as PasswordConfirm;
    const wrong = wrongPassword(body.password);
    if (wrong) return wrong;
    let result: ExternalService | undefined;
    update((s) => {
      const service = findService(s, String(params["key"]));
      if (!service?.switch) return;
      service.switch = {
        ...service.switch,
        disabled: false,
        reason: null,
        changed_at: MOCK_NOW,
        changed_by: "Демо Админов",
      };
      result = service;
    });
    return result ? HttpResponse.json(result) : failure(404, "NOT_FOUND", "Не найдено.", "crm");
  }),

  // --- Модели ИИ
  http.put("*/admin/integrations/models/providers/:provider/key", async ({ request, params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as ProviderKeyIn;
    const wrong = wrongPassword(body.password);
    if (wrong) return wrong;
    const provider = String(params["provider"]);
    // Одна операция: ключ ложится на все роли провайдера, модели ролей не меняются
    const roles: AiModelChange[] = [];
    update((s) => {
      for (const model of s.models.filter((m) => m.provider === provider)) {
        model.health = "ok";
        model.health_detail = null;
        model.checked_at = MOCK_NOW;
        model.key_source = "crm";
        model.key_last4 = last4(body.api_key);
        roles.push({
          alias: model.alias,
          provider,
          model: (model.model ?? "").replace(`${provider}/`, ""),
          key_source: "crm",
          reindex_required: false,
          quality_check_recommended: false,
        });
      }
      const vendor = findService(s, `vendor.${provider}`);
      if (vendor) settleOk(vendor, MOCK_NOW, "Ошибок за 15 минут нет");
    });
    if (roles.length === 0) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    markStepDone("models"); // шаг «Модели ИИ» (W15-H4)
    return HttpResponse.json({ provider, roles, checked: true });
  }),
  http.get("*/admin/integrations/models", () => {
    const denied = guard("read");
    if (denied) return denied;
    return HttpResponse.json({ items: readIntegrations().models });
  }),
  http.put("*/admin/integrations/models/:alias", async ({ request, params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as AiModelChangeIn;
    const wrong = wrongPassword(body.password);
    if (wrong) return wrong;
    const alias = String(params["alias"]);
    const name = normalizeModel(body.provider, body.model);
    if (name === null) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "crm", {
        fields: ["model"],
      });
    }
    let changed: AiModel | undefined;
    update((s) => {
      const model = s.models.find((m) => m.alias === alias);
      if (!model) return;
      model.provider = body.provider;
      model.model = `${body.provider}/${name}`;
      model.health = "ok";
      model.health_detail = null;
      model.checked_at = MOCK_NOW;
      model.key_source = body.api_key ? "crm" : "env";
      model.key_last4 = body.api_key ? last4(body.api_key) : null;
      changed = model;
      const vendor = findService(s, `vendor.${body.provider}`);
      if (vendor && !s.models.some((m) => m.provider === body.provider && m.health === "problem")) {
        settleOk(vendor, MOCK_NOW, "Ошибок за 15 минут нет");
      }
    });
    if (!changed) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    return HttpResponse.json({
      alias,
      provider: body.provider,
      model: name,
      key_source: body.api_key ? "crm" : "env",
      reindex_required: alias === "embed-model",
      quality_check_recommended: true,
    });
  }),
  http.post("*/admin/integrations/models/:alias/reset", async ({ request, params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as PasswordConfirm;
    const wrong = wrongPassword(body.password);
    if (wrong) return wrong;
    const alias = String(params["alias"]);
    const model = readIntegrations().models.find((m) => m.alias === alias);
    if (!model) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    update((s) => {
      const row = s.models.find((m) => m.alias === alias);
      if (row) {
        row.key_source = "env";
        row.key_last4 = null;
      }
    });
    return HttpResponse.json({
      alias,
      provider: model.provider ?? "anthropic",
      model: model.model ?? "claude-demo-chat",
      key_source: "env",
      reindex_required: alias === "embed-model",
      quality_check_recommended: false,
    });
  }),
  http.post("*/admin/integrations/models/:alias/test", ({ params }) => {
    const denied = guard("full");
    if (denied) return denied;
    const alias = String(params["alias"]);
    const model = readIntegrations().models.find((m) => m.alias === alias);
    if (!model) return failure(404, "NOT_FOUND", "Не найдено.", "crm");
    const ok = model.health !== "problem";
    return HttpResponse.json({
      alias,
      ok,
      detail: ok ? null : "401: ключ отклонён провайдером",
      latency_ms: ok ? 880 : 210,
      cost_usd: ok ? 0.0002 : null,
    });
  }),

  // --- Расходы, бэкапы, состояние
  http.get("*/admin/integrations/spend", ({ request }) => {
    const denied = guard("read");
    if (denied) return denied;
    const days = Number(new URL(request.url).searchParams.get("days") ?? 30);
    return HttpResponse.json(spendReport(days));
  }),
  http.get("*/admin/integrations/ai-spend", ({ request }) => {
    const denied = guard("read");
    if (denied) return denied;
    const group = (new URL(request.url).searchParams.get("group") ?? "day") as
      "day" | "system" | "feature" | "model";
    return HttpResponse.json(aiSpendReport(group));
  }),
  http.get(
    "*/admin/integrations/backups",
    () => guard("read") ?? HttpResponse.json(readIntegrations().backups),
  ),
  http.post("*/admin/integrations/backups", () => {
    const denied = guard("full");
    if (denied) return denied;
    const state = update((s) => {
      s.backups = { ...s.backups, requested_at: MOCK_NOW };
    });
    return HttpResponse.json(state.backups, { status: 202 });
  }),
  http.get("*/admin/integrations/system", () => {
    const denied = guard("read");
    if (denied) return denied;
    const components = [...readIntegrations().components].sort(
      (a, b) =>
        ["fail", "warn", "unknown", "ok"].indexOf(a.status) -
        ["fail", "warn", "unknown", "ok"].indexOf(b.status),
    );
    return HttpResponse.json({
      checked_at: MOCK_NOW,
      status:
        worst(components.map((c) => c.status)) === "off"
          ? "unknown"
          : worst(components.map((c) => c.status)),
      components,
    });
  }),
];
