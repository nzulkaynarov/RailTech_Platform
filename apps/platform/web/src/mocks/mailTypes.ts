import { HttpResponse, http } from "msw";

import { allows } from "../app/rbac.generated";
import type {
  DictionaryItem,
  InboundMailType,
  InboundMailTypeColor,
  InboundMailTypeDefaultAction,
  InboundMailTypeIcon,
  InboundMailTypeSource,
  MailSenderRule,
  MailSenderRuleIn,
} from "../shared/api/generated/model";
import { readDictionaries } from "./dictionaries";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки типов входящих писем (MAIL-TYPES): правила «отправитель или домен → тип» и разбор типа письма по справочнику
 * `mail-types` (его значения — в `dictionaries.ts`, как у CRM). Правило применяется к открытым «Новым» письмам, где тип не
 * выбирал человек, и побеждает помощника. Живёт в `localStorage` страницы. Данные вымышленные.
 */
const KEY = "rt-pf-mock-mail-rules";

/** Публичные почтовые сервисы: правило на такой домен получает предупреждение (как у CRM). */
const PUBLIC_DOMAINS: ReadonlySet<string> = new Set([
  "gmail.com",
  "mail.ru",
  "yandex.ru",
  "outlook.com",
]);

let memory: MailSenderRule[] | null = null;

export function readRules(): MailSenderRule[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as MailSenderRule[];
  } catch {
    // Хранилище недоступно — состояние в памяти.
  }
  return memory ?? [];
}

function writeRules(rules: MailSenderRule[]): void {
  memory = rules;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(rules));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetMailTypesMock(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}

/** Тип письма для ответа: актуальные название, цвет и действие из справочника; удалённого кода нет. */
export function resolveType(code: string, source: InboundMailTypeSource): InboundMailType | null {
  const row = readDictionaries()["mail-types"].find((item) => item.code === code);
  if (!row) return null;
  return typeOf(row, source);
}

function typeOf(row: DictionaryItem, source: InboundMailTypeSource): InboundMailType {
  return {
    code: row.code,
    name: row.name,
    color: String(row.attrs["color"]) as InboundMailTypeColor,
    icon: String(row.attrs["icon"]) as InboundMailTypeIcon,
    default_action: String(row.attrs["default_action"]) as InboundMailTypeDefaultAction,
    letter_kind: typeof row.attrs["letter_kind"] === "string" ? row.attrs["letter_kind"] : null,
    active: row.active,
    source,
  };
}

/** Адрес или домен в одну форму, как CRM (`*@soliq.uz`, `@soliq.uz`, `soliq.uz`); иначе `null`. */
export function normalizePattern(raw: string): string | null {
  let text = raw.trim().toLowerCase();
  if (text.startsWith("*@")) text = text.slice(2);
  else if (text.startsWith("@")) text = text.slice(1);
  const domain = /^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}$/;
  const email = /^[^@\s<>,;]{1,64}@([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}$/;
  return email.test(text) || domain.test(text) ? text : null;
}

function failure(status: number, code: string, message: string, details?: Record<string, unknown>) {
  return HttpResponse.json(
    { code, message, source: status === 403 ? "bff" : "crm", ...(details ? { details } : {}) },
    { status },
  );
}

const forbidden = () => failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");

function allowed(resource: "admin", level: "read" | "full"): boolean {
  const session = readSession();
  const me = session ? buildMe({ ...session, activeRole: null }) : null;
  return Boolean(me && allows(me.resources, resource, level));
}

function canReadRules(): boolean {
  const session = readSession();
  const me = session ? buildMe({ ...session, activeRole: null }) : null;
  return Boolean(
    me &&
    (allows(me.resources, "crm.leads.triage", "read") || allows(me.resources, "admin", "read")),
  );
}

/** Применение правила к открытым «Новым»: подставляется вызывающим (письма живут в `inboundMail.ts`). */
let apply: (pattern: string, code: string, exceptId: number | null) => number = () => 0;
export function setRuleApplier(fn: typeof apply): void {
  apply = fn;
}

export const mailTypesHandlers = [
  http.get("*/mail-sender-rules", () => {
    if (!readSession()) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    if (!canReadRules()) return forbidden();
    return HttpResponse.json({ items: readRules() });
  }),
  http.post("*/mail-sender-rules", async ({ request }) => {
    if (!allowed("admin", "full")) return forbidden();
    const body = (await request.json()) as MailSenderRuleIn;
    const pattern = normalizePattern(body.pattern);
    if (!pattern)
      return failure(422, "VALIDATION_FAILED", "Укажите адрес или домен.", { fields: ["pattern"] });
    const type = readDictionaries()["mail-types"].find((i) => i.code === body.type_code);
    if (!type)
      return failure(422, "VALIDATION_FAILED", "Такого типа нет.", { fields: ["type_code"] });
    if (!type.active)
      return failure(409, "CONFLICT", "Тип отключён.", { reason: "mail_type_inactive" });
    if (readRules().some((r) => r.pattern === pattern))
      return failure(409, "CONFLICT", "Правило уже есть.", { reason: "mail_rule_exists" });
    const rule: MailSenderRule = {
      id: Math.max(0, ...readRules().map((r) => r.id)) + 1,
      pattern,
      type_code: type.code,
      created_at: new Date().toISOString(),
      created_by: "Администратор Демо",
    };
    writeRules([...readRules(), rule]);
    const applied = apply(pattern, type.code, body.mail_id ?? null);
    const domain = pattern.split("@").pop() ?? "";
    return HttpResponse.json(
      { ...rule, applied, caution: PUBLIC_DOMAINS.has(domain) ? "public_domain" : null },
      { status: 201 },
    );
  }),
  http.delete("*/mail-sender-rules/:id", ({ params }) => {
    if (!allowed("admin", "full")) return forbidden();
    const id = Number(params["id"]);
    if (!readRules().some((r) => r.id === id)) return failure(404, "NOT_FOUND", "Правила нет.");
    writeRules(readRules().filter((r) => r.id !== id));
    return new HttpResponse(null, { status: 204 });
  }),
];
