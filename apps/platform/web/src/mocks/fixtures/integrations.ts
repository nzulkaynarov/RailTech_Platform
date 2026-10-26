import type {
  AiModel,
  AiSpendReport,
  BackupsStatus,
  BotProfile,
  BotProfilePublish,
  ErpConnector,
  ExternalService,
  MailLogItem,
  SmtpConnector,
  SpendReport,
  SystemComponent,
  TelegramChannel,
  TelegramConnector,
} from "../../shared/api/generated/model";

/**
 * Состояние Admin · Внешние интеграции для MSW (W13-A1). Вымышленное: домен `.example`, ни настоящих токенов, ни паролей.
 * Секретов в состоянии нет вовсе — как и в ответах BFF, только «задан» и последние 4 символа. Хранится в `localStorage`
 * страницы (как сессия мока), без хранилища — копия в памяти. Время фиксировано, чтобы снимки и e2e не плавали.
 */
const KEY = "rt-pf-mock-integrations";

export const MOCK_NOW = "2026-10-26T09:12:00Z";
const EARLIER = "2026-10-26T09:05:00Z";
const YESTERDAY = "2026-10-25T09:05:00Z";

export interface IntegrationsMock {
  erp: ErpConnector;
  telegram: TelegramConnector;
  channels: TelegramChannel[];
  profile: BotProfile;
  published: BotProfilePublish | null;
  smtp: SmtpConnector;
  mailLog: MailLogItem[];
  services: ExternalService[];
  models: AiModel[];
  backups: BackupsStatus;
  components: SystemComponent[];
}

function text(ru: string, uz: string, en: string) {
  return { ru, uz, en };
}

function service(
  key: string,
  title: string,
  purpose: string,
  over: Partial<ExternalService> = {},
): ExternalService {
  return {
    key,
    title,
    purpose,
    system: "crm",
    source: "crm",
    check: "Проверка без платных вызовов",
    frequency: "minute",
    status: "ok",
    summary: "Работает",
    error: null,
    hint: null,
    fix_card: null,
    checked_at: EARLIER,
    stale: false,
    latency_ms: 120,
    uptime_24h: 0.999,
    uptime_7d: 0.998,
    checks_24h: 1440,
    failures_24h: 1,
    p95_ms_24h: 310,
    switch: null,
    incident: null,
    ...over,
  };
}

function toggle(kind: "vendor" | "langfuse" | "mail" | "telegram" | "erp", effect: string) {
  return {
    kind,
    available: true,
    disabled: false,
    effect,
    problem: null,
    reason: null,
    changed_at: null,
    changed_by: null,
  };
}

function seedServices(): ExternalService[] {
  return [
    service("telegram", "Telegram Bot API", "Клиентский бот, канал команды и личные уведомления", {
      summary: "Токен принят, очередь обновлений пуста",
      fix_card: "telegram",
      switch: toggle("telegram", "Бот перестанет отвечать клиентам; сообщения встанут в очередь"),
    }),
    service(
      "mail",
      "Почтовый релей (SMTP)",
      "Письма сотрудникам: приглашение, сброс пароля, оповещения",
      {
        status: "warn",
        summary: "В очереди 3 письма дольше 15 минут",
        error: "queue_growing",
        hint: "Проверьте связь с почтовым сервером в карточке «Почта».",
        fix_card: "mail",
        switch: toggle("mail", "Письма будут копиться в журнале и не уйдут, пока сервис выключен"),
      },
    ),
    service("litellm", "Шлюз моделей (LiteLLM)", "Единая точка вызова моделей ИИ для CRM и ERP", {
      system: "ensemble",
      summary: "Шлюз отвечает",
      fix_card: "models",
    }),
    service("vendor.anthropic", "Anthropic (Claude)", "Диалог и квалификатор", {
      summary: "Ошибок за 15 минут нет",
      fix_card: "models",
      switch: toggle("vendor", "Диалоги перейдут на запасную модель"),
    }),
    service("vendor.openai", "OpenAI", "Поиск по базе знаний (эмбеддинги)", {
      status: "fail",
      summary: "Ключ отклонён провайдером (401)",
      error: "401",
      hint: "Смените ключ в карточке «Модели ИИ».",
      fix_card: "models",
      incident: {
        id: 7,
        started_at: "2026-10-26T08:40:00Z",
        ended_at: null,
        duration_s: null,
        summary: "Ключ провайдера отклонён",
        last_error: "401 Unauthorized",
      },
      switch: toggle(
        "vendor",
        "Поиск по базе знаний перестанет работать: честный отказ вместо ответа",
      ),
    }),
    service("langfuse", "Langfuse (журнал работы ИИ)", "Трейсы диалогов и стоимость", {
      status: "off",
      summary: "Не подключён",
      checked_at: null,
      uptime_24h: null,
      uptime_7d: null,
      latency_ms: null,
      p95_ms_24h: null,
      checks_24h: 0,
      failures_24h: 0,
      switch: toggle("langfuse", "Трейсы перестанут записываться"),
    }),
    service("s3", "Хранилище файлов (S3)", "Документы клиентов, база знаний и вложения", {
      system: "ensemble",
      summary: "Хранилище отвечает; занято 12 ГБ",
    }),
    service("erp_sync", "Синхронизация сотрудников с ERP", "Доступ сотрудников к ERP", {
      system: "ensemble",
      summary: "Задачи провижининга выполняются",
      fix_card: "erp",
    }),
    service(
      "erp_handoff",
      "Передача клиентов в ERP",
      "Компания, контакты и заявка клиента появляются в ERP",
      {
        system: "ensemble",
        summary: "Зависших передач нет",
      },
    ),
    service("erp_events", "События из ERP", "События ERP на шине", {
      system: "ensemble",
      summary: "Необработанных событий нет",
      fix_card: "erp",
    }),
    service("backup", "Хранилище резервных копий", "Ежедневная копия базы и файлов", {
      summary: "Сервис копирования жив, копия свежая",
      fix_card: "storage",
    }),
    service("erp.mail", "Почта ERP", "Письма клиентам и сотрудникам бэк-офиса из ERP", {
      system: "erp",
      source: "erp",
      frequency: "erp",
      status: "unknown",
      summary: "Нет данных: эта версия ERP не передаёт состояние своих внешних сервисов",
      checked_at: null,
      uptime_24h: null,
      uptime_7d: null,
      latency_ms: null,
      p95_ms_24h: null,
    }),
  ];
}

function seedMailLog(): MailLogItem[] {
  const row = (
    id: number,
    status: MailLogItem["status"],
    subject: string,
    to: string,
    over: Partial<MailLogItem> = {},
  ): MailLogItem => ({
    id,
    to_email: to,
    subject,
    template: "invite",
    status,
    error: null,
    attempts: 1,
    created_at: EARLIER,
    sent_at: status === "sent" ? EARLIER : null,
    ...over,
  });
  return [
    row(5, "queued", "Сброс пароля", "colleague5@demo.example", {
      created_at: "2026-10-26T08:50:00Z",
    }),
    row(4, "queued", "Приглашение в Платформу", "colleague4@demo.example", {
      created_at: "2026-10-26T08:40:00Z",
    }),
    row(3, "sent", "Приглашение в Платформу", "colleague3@demo.example", {
      sent_at: YESTERDAY,
      created_at: YESTERDAY,
    }),
    row(2, "failed", "Оповещение о сбое сервиса", "colleague2@demo.example", {
      error: "smtp_unavailable",
      attempts: 3,
      created_at: YESTERDAY,
    }),
    row(1, "sent", "Приглашение в Платформу", "colleague1@demo.example", {
      sent_at: YESTERDAY,
      created_at: YESTERDAY,
    }),
  ];
}

function seedModels(): AiModel[] {
  const base = { checked_at: EARLIER, health_detail: null };
  const crmKey = { key_source: "crm", key_last4: "77aa" } as const;
  const envKey = { key_source: "env", key_last4: null } as const;
  return [
    {
      alias: "dialog-model",
      provider: "anthropic",
      model: "claude-demo-chat",
      health: "ok",
      today_usd: 1.25,
      ...crmKey,
      ...base,
    },
    {
      alias: "qualifier-model",
      provider: "anthropic",
      model: "claude-demo-small",
      health: "ok",
      today_usd: 0.31,
      ...envKey,
      ...base,
    },
    {
      alias: "fallback-model",
      provider: "gemini",
      model: "gemini-demo-flash",
      health: "ok",
      today_usd: 0,
      key_source: null,
      key_last4: null,
      ...base,
    },
    {
      alias: "embed-model",
      provider: "openai",
      model: "embedding-demo",
      health: "problem",
      health_detail: "401: ключ отклонён провайдером",
      checked_at: EARLIER,
      today_usd: 0.04,
      ...crmKey,
    },
  ];
}

export function seedIntegrations(): IntegrationsMock {
  return {
    erp: {
      base_url: "http://erp-backend:8000",
      configured: true,
      mode: "erp",
      paired: true,
      previous_secret_until: null,
      rotation_pending: false,
      secrets_enabled: true,
      suggested_base_url: "http://erp-backend:8000",
      token_configured: true,
      token_last4: "9f3c",
      token_updated_at: "2026-10-20T10:30:00Z",
      webhook_secret_configured: true,
      webhook_secret_last4: "77de",
    },
    telegram: {
      channel_id: -1001,
      channel_title: "Команда RailTech (демо)",
      configured: true,
      last4: "Qw7x",
      last_error: null,
      mode: "polling",
      running: true,
      secrets_enabled: true,
      updated_at: "2026-10-20T10:35:00Z",
      username: "demo_railtech_bot",
    },
    channels: [
      {
        chat_id: -1001,
        title: "Команда RailTech (демо)",
        chat_type: "supergroup",
        detected_at: "2026-10-20T10:40:00Z",
      },
      {
        chat_id: -1002,
        title: "Склад и логистика (демо)",
        chat_type: "group",
        detected_at: "2026-10-24T15:20:00Z",
      },
    ],
    profile: {
      name: text("RailTech Помощник", "RailTech Yordamchi", "RailTech Assistant"),
      short_description: text(
        "Отвечает на вопросы о поставках",
        "Yetkazib berish haqidagi savollarga javob beradi",
        "Answers questions about supplies",
      ),
      description: text(
        "Помогу узнать статус заявки, найти документы и связаться с менеджером.",
        "Ariza holatini bilishga, hujjatlarni topishga va menejer bilan bog‘lanishga yordam beraman.",
        "I can check the status of a request, find documents and contact a manager.",
      ),
    },
    published: { ok: true, at: "2026-10-20T10:50:00Z", changed: 3, error: null, retry_after: null },
    smtp: {
      configured: true,
      from_email: "noreply@demo.example",
      from_name: "RailTech (демо)",
      host: "smtp.demo.example",
      password_configured: true,
      password_last4: "k3Zp",
      password_updated_at: "2026-10-20T10:20:00Z",
      port: 587,
      secrets_enabled: true,
      security: "starttls",
      username: "mailer",
    },
    mailLog: seedMailLog(),
    services: seedServices(),
    models: seedModels(),
    backups: {
      available: true,
      can_request: true,
      daemon_alive: true,
      databases: [
        { name: "crm", last_success_at: "2026-10-26T03:00:00Z" },
        { name: "erp", last_success_at: "2026-10-26T03:05:00Z" },
      ],
      error: null,
      items: [
        { name: "crm-2026-10-26.dump", at: "2026-10-26T03:00:00Z", size_bytes: 52_428_800 },
        { name: "erp-2026-10-26.dump", at: "2026-10-26T03:05:00Z", size_bytes: 31_457_280 },
        { name: "crm-2026-10-25.dump", at: "2026-10-25T03:00:00Z", size_bytes: 51_380_224 },
      ],
      last_success_at: "2026-10-26T03:05:00Z",
      request_stuck: false,
      requested_at: null,
      source: "volume",
      stale: false,
    },
    components: [
      {
        key: "queue",
        title: "Очередь задач",
        status: "warn",
        reason: "Очередь отстаёт на 40 секунд",
        checked_at: EARLIER,
      },
      {
        key: "database",
        title: "База данных CRM",
        status: "ok",
        reason: "Отвечает за 4 мс",
        checked_at: EARLIER,
      },
      {
        key: "bot",
        title: "Telegram-бот",
        status: "ok",
        reason: "Процесс работает",
        checked_at: EARLIER,
      },
      { key: "litellm", title: "Шлюз моделей", status: "ok", reason: "Готов", checked_at: EARLIER },
      {
        key: "s3",
        title: "Хранилище файлов",
        status: "ok",
        reason: "Отвечает",
        checked_at: EARLIER,
      },
      {
        key: "backup",
        title: "Резервные копии",
        status: "ok",
        reason: "Копия свежая",
        checked_at: EARLIER,
      },
    ],
  };
}

let memory: IntegrationsMock | null = null;

export function readIntegrations(): IntegrationsMock {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as IntegrationsMock) : seedIntegrations();
  } catch {
    // Хранилище недоступно — состояние живёт в памяти.
    memory ??= seedIntegrations();
    return memory;
  }
}

export function writeIntegrations(state: IntegrationsMock): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetIntegrations(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего очищать.
  }
}

/** Расходы бота: фиксированный отчёт на `days` дней. */
export function spendReport(days: number): SpendReport {
  const series = Array.from({ length: Math.min(days, 10) }, (_, index) => {
    const day = new Date(Date.UTC(2026, 9, 26 - index));
    return {
      day: day.toISOString().slice(0, 10),
      work_usd: Number((1.1 + (index % 3) * 0.2).toFixed(2)),
      test_usd: Number((0.1 + (index % 2) * 0.05).toFixed(2)),
    };
  }).reverse();
  return {
    avg_per_lead_usd: 0.083,
    by_kind: [
      { key: "chat", cost_usd: 24.4, calls: 640 },
      { key: "embedding", cost_usd: 1.6, calls: 410 },
    ],
    by_purpose: [
      { key: "dialog", cost_usd: 19.2, calls: 480 },
      { key: "qualifier", cost_usd: 5.2, calls: 160 },
      { key: "knowledge", cost_usd: 1.6, calls: 410 },
    ],
    daily_usd: 5,
    days,
    leads: Math.round(days * 3.2),
    providers: [
      { provider: "anthropic", spent_usd: 3.8, limit_usd: 10 },
      { provider: "openai", spent_usd: 0.5, limit_usd: 5 },
      { provider: "gemini", spent_usd: 0, limit_usd: 0 },
    ],
    series,
    today_usd: 1.6,
    total_usd: Number((days * 0.87).toFixed(2)),
  };
}

export function aiSpendReport(group: AiSpendReport["group"]): AiSpendReport {
  const totals = {
    calls: 1250,
    failed_calls: 18,
    fallback_calls: 6,
    input_tokens: 2_100_000,
    output_tokens: 410_000,
    cost_usd: 26.0,
  };
  const keys: Record<AiSpendReport["group"], string[]> = {
    day: ["2026-10-24", "2026-10-25", "2026-10-26"],
    system: ["crm", "erp"],
    feature: ["dialog", "qualifier", "quote-draft"],
    model: ["dialog-model", "embed-model", "draft-model"],
  };
  return {
    date_from: "2026-09-27",
    date_to: "2026-10-26",
    erp_connected: true,
    fetched_at: MOCK_NOW,
    group,
    overruns: [{ system: "crm", day: "2026-10-22", cost_usd: 5.4, daily_usd: 5 }],
    rows: keys[group].map((key, index) => ({
      key,
      calls: 500 - index * 120,
      failed_calls: index,
      fallback_calls: 0,
      input_tokens: 900_000 - index * 200_000,
      output_tokens: 170_000 - index * 40_000,
      cost_usd: Number((11 - index * 3).toFixed(2)),
    })),
    systems: [
      {
        system: "crm",
        connected: true,
        daily_usd: 5,
        days_over: 1,
        fallback_calls: 6,
        over_today: false,
        period_calls: 980,
        period_usd: 20.5,
        today_calls: 31,
        today_usd: 1.6,
      },
      {
        system: "erp",
        connected: true,
        daily_usd: 3,
        days_over: 0,
        fallback_calls: 0,
        over_today: false,
        period_calls: 270,
        period_usd: 5.5,
        today_calls: 9,
        today_usd: 0.4,
      },
    ],
    timezone: "Asia/Tashkent",
    totals,
    truncated: false,
  };
}
