import type {
  AiModel,
  ExternalService,
  IntegrationStatus,
  ServiceGroup,
  ServiceState,
} from "../../shared/api/generated/model";

/**
 * Состояние, причина и группы «Требует внимания» для MSW (W15-H3): те же правила, что в CRM (`external_cause`), в
 * упрощённом виде. Вымышленные данные: тексты ключей и ответов провайдера выдуманы, значений секретов нет.
 */
export const STATE_OF_STATUS: Record<IntegrationStatus, ServiceState> = {
  ok: "ok",
  fail: "broken",
  warn: "degraded",
  unknown: "not_checked",
  off: "not_configured",
};

const FUNCTIONS: Record<string, string> = {
  "dialog-model": "диалог с клиентом",
  "qualifier-model": "оценка лидов",
  "fallback-model": "запасная модель",
  "embed-model": "поиск по базе знаний",
  "judge-model": "проверка качества ответов",
};

const VENDOR: Record<string, string> = {
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  openai: "OpenAI",
};

const OWNER_MESSAGE =
  "Здравствуйте!\nВ Платформе (RailTech) сбой: {headline}.\nНе работают: {affected}.\nНачалось: {since}.\nЧто нужно: выпустить новый ключ API у провайдера и передать его администратору Платформы.";

function leftTime(iso: string): string {
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)} ${iso.slice(11, 16)}`;
}

/** Состояние сервиса на чтении: выключенный вручную — «Выключено намеренно», остальное — как записано. */
export function withState(service: ExternalService): ExternalService {
  if (service.switch?.disabled) {
    return { ...service, state: "disabled", owner: null, action: null, more_actions: [] };
  }
  return service;
}

/** Починили: сервис снова «Работает», причина и «с …» снимаются, в журнале остаётся «восстановлено в …». */
export function settleOk(service: ExternalService, at: string, summary: string): void {
  service.status = "ok";
  service.state = "ok";
  service.summary = summary;
  service.error = null;
  service.hint = null;
  service.incident = null;
  service.checked_at = at;
  service.owner = null;
  service.action = null;
  service.more_actions = [];
  service.since = null;
  service.cause_key = `${service.key}:ok`;
  service.last_recovered_at = at;
}

function headlineOf(first: ExternalService): string {
  const match = /^vendor\.(.+):key_rejected$/.exec(first.cause_key);
  if (match?.[1]) return `Ключ ${VENDOR[match[1]] ?? match[1]} отклонён`;
  return first.summary;
}

/** Не-`ok` сервисы, свёрнутые по причине: тот же порядок, что у CRM (сломано → перебои → не настроено → …). */
export function groupsOf(
  services: ExternalService[],
  models: AiModel[],
  now: string,
): ServiceGroup[] {
  const order: ServiceState[] = [
    "broken",
    "degraded",
    "not_configured",
    "not_checked",
    "expected",
    "disabled",
  ];
  const byCause = new Map<string, ExternalService[]>();
  for (const service of services.map(withState)) {
    if (service.state === "ok") continue;
    byCause.set(service.cause_key, [...(byCause.get(service.cause_key) ?? []), service]);
  }
  const groups: ServiceGroup[] = [];
  for (const [id, members] of byCause) {
    const first = members[0];
    if (!first) continue;
    const vendor = /^vendor\.(.+):/.exec(id)?.[1];
    const affected = vendor
      ? models.filter((m) => m.provider === vendor).map((m) => FUNCTIONS[m.alias] ?? m.alias)
      : [];
    const since =
      members
        .map((m) => m.since)
        .filter((v): v is string => Boolean(v))
        .sort()[0] ?? null;
    const headline = headlineOf(first);
    const messageFor = first.owner === "owner" || first.owner === "hosting";
    groups.push({
      id,
      state: first.state,
      owner: first.owner,
      action: first.action,
      more_actions: first.more_actions,
      headline,
      detail: first.hint,
      affected,
      service_keys: members.map((m) => m.key),
      titles: members.map((m) => m.title),
      since,
      technical: members.map((m) => m.error).filter((v): v is string => Boolean(v)),
      message: messageFor
        ? first.owner === "hosting"
          ? `Здравствуйте!\nВ Платформе (RailTech) сбой: ${headline}.\nНачалось: ${leftTime(since ?? now)}.\nЧто нужно: запустить docling вместе с ансамблем.`
          : OWNER_MESSAGE.replace("{headline}", headline)
              .replace("{affected}", affected.join(", "))
              .replace("{since}", leftTime(since ?? now))
        : null,
      fix_card: first.fix_card,
      flaps_24h: Math.max(...members.map((m) => m.flaps_24h)),
    });
  }
  return groups.sort((a, b) => order.indexOf(a.state) - order.indexOf(b.state));
}
