import { RT_TAG_TEXT } from "../../app/tokens.generated";
import { PF_COLORS, TAG_TEXT } from "../../app/theme";

/**
 * Цвета тегов статусов (SPEC-v3 §5.2): blue, green, gold, red, purple, cyan, default. Цвет текста — всегда из колонки
 * «текст» (контраст ≥ 4.5:1 на фоне тега), фон и рамка — светлые значения antd. Статус не передаётся только цветом:
 * у тега всегда есть слово (SPEC-v3 §5.2).
 */
export const STATUS_TONES = ["blue", "green", "gold", "red", "purple", "cyan", "default"] as const;
export type StatusTone = (typeof STATUS_TONES)[number];

export interface ToneStyle {
  color: string;
  background: string;
  borderColor: string;
}

export const TONE_STYLE: Record<StatusTone, ToneStyle> = {
  blue: { color: RT_TAG_TEXT["blue"] ?? "", background: "#e6f4ff", borderColor: "#91caff" },
  green: { color: RT_TAG_TEXT["green"] ?? "", background: "#f6ffed", borderColor: "#b7eb8f" },
  gold: { color: RT_TAG_TEXT["gold"] ?? "", background: "#fffbe6", borderColor: "#ffe58f" },
  red: { color: RT_TAG_TEXT["red"] ?? "", background: "#fff2f0", borderColor: "#ffccc7" },
  purple: { color: RT_TAG_TEXT["purple"] ?? "", background: "#f9f0ff", borderColor: "#d3adf7" },
  cyan: { color: RT_TAG_TEXT["cyan"] ?? "", background: "#e6fffb", borderColor: "#87e8de" },
  default: { color: TAG_TEXT.default, background: "#fafafa", borderColor: PF_COLORS.border },
};

/** Семь стадий заявки SPEC-v3 §2.3 (код для интеграции) и «Отказ». */
export const STAGES = [
  "REQUEST",
  "RESOLUTION",
  "CALCULATION",
  "QUOTE",
  "CONTRACT",
  "PAYMENT",
  "DONE",
] as const;
export type StageCode = (typeof STAGES)[number];
export type StageOrLost = StageCode | "LOST";

/**
 * Смысл статуса → цвет (SPEC-v3 §5.2; UX-2b). Один смысл — один цвет во всех модулях; модуль цвет не выбирает, а называет
 * вид и код (`<StatusTag kind status>`). Расхождение с ТЗ UX-2b: «Черновик» по SPEC-v3 §5.2 — `colorWarning` (золотой),
 * а не серый; черновик и «проект» документа — золотые.
 */
export const MEANING_TONE = {
  /** Ждёт решения или действия сотрудника: на согласовании, у директора, возвращено, платёжка получена, в очереди */
  waiting: "gold",
  /** Черновик, проект документа (SPEC-v3 §5.2 — как «ждёт решения») */
  draft: "gold",
  /** Одобрено, готово, подписано, оплачено, работает */
  done: "green",
  /** Отклонено, отказ, просрочено, срок истёк, сбой */
  failed: "red",
  /** Служебные записки, внутренние чаты */
  memo: "purple",
  /** В работе, новое, отправлено или выставлено клиенту — ждём его ответа */
  active: "blue",
  /** Telegram и внешние каналы */
  external: "cyan",
  /** Отменено, архив, выключено, пропущено */
  closed: "default",
  /** Нет данных или не применимо: «не начат», «нет визы», «без срока», «не проверено» */
  neutral: "default",
} as const satisfies Record<string, StatusTone>;
export type StatusMeaning = keyof typeof MEANING_TONE;

const W = MEANING_TONE.waiting;
const DR = MEANING_TONE.draft;
const OK = MEANING_TONE.done;
const NO = MEANING_TONE.failed;
const MEMO = MEANING_TONE.memo;
const GO = MEANING_TONE.active;
const EXT = MEANING_TONE.external;
const OFF = MEANING_TONE.closed;
const NONE = MEANING_TONE.neutral;

/**
 * Единственная карта «вид → код статуса → цвет» Платформы (UX-2b). Ключ — код из ответа BFF; слово статуса задаёт модуль
 * (`children`) или словарь `dictionary:status.<вид>.<код>` для документов SPEC-v3 §2.4 (`DICTIONARY_STATUS`). Один и тот же
 * код в разных видах — один цвет (тест `statuses.test.ts`). Новых локальных карт в модулях нет: линтер запрещает
 * `StatusTone`/`TONE_STYLE` и вычисляемый `tone` вне `shared` (platform-frontend.md §5).
 */
export const STATUS_TONE = {
  /** Входящее письмо */
  incoming: { registered: GO, awaiting_resolution: W, resolved: OK, returned: W, rejected: NO },
  /**
   * КП — одна карта для EDS («КП на одобрение», реестр, проект) и ERP (состояние КП в расчёте): «у директора» и «черновик ·
   * отправка заблокирована» — ждут решения, «одобрено» — зелёное везде.
   */
  quote: {
    draft: DR,
    not_started: NONE,
    in_progress: GO,
    open: W,
    at_director: W,
    revision: W,
    returned: W,
    approved: OK,
    sent: GO,
    accepted: OK,
    declined: NO,
    rejected: NO,
    expired: NO,
  },
  /** Договор (словарь SPEC-v3 §2.4 и коды проекта D2-5) */
  contract: {
    draft: DR,
    project: DR,
    agreed: GO,
    client_agreed: GO,
    issued: GO,
    issued_at_operator: GO,
    signed: OK,
    rejected: NO,
    cancelled: OFF,
  },
  /** Счёт («не выставлен» — `draft`, «к выставлению» — `to_issue`) */
  invoice: {
    draft: DR,
    to_issue: W,
    issued: GO,
    proof_received: W,
    partially_paid: W,
    partial: W,
    paid: OK,
    overdue: NO,
    cancelled: OFF,
  },
  /** Акт */
  act: { draft: DR, project: DR, issued: GO, signed: OK, returned: W, cancelled: OFF },
  /** Служебная записка и внутренние документы EDS (реестр, согласование, «к оплате») */
  memo: {
    draft: DR,
    pending: W,
    on_approval: W,
    open: W,
    approved: OK,
    rejected: NO,
    returned: W,
    passed_to_accountant: GO,
    to_accountant: GO,
    to_pay: GO,
    sent: GO,
    paid: OK,
  },
  /** Платёжка клиента к счёту */
  proof: { PENDING: W, CONFIRMED: OK, EXTRA: NONE },
  /** Лид (`platform_status`, CRM-02; «Отказ» — как отказ по заявке, красный) */
  lead: { new: GO, dialog: EXT, wants_quote: W, no_answer: NO, client: OK, lost: NO },
  /** Стадия заявки/проекта */
  stage: {
    REQUEST: GO,
    RESOLUTION: GO,
    CALCULATION: GO,
    QUOTE: GO,
    CONTRACT: GO,
    PAYMENT: GO,
    DONE: OK,
    LOST: NO,
  },
  /** Виза группы в расчёте (склад, снабжение, гл. инженер) */
  visa: { done: OK, waiting: W, none: NONE },
  /** Запрос цены поставщику */
  priceRequest: { sent: GO, answered: OK, failed: NO },
  /** Заказ поставщику */
  supplierOrder: { draft: DR, sent: GO, confirmed: GO, received: OK, cancelled: OFF },
  /** Остаток на складе: свободно, нет свободного, в резерве */
  stock: { free: OK, none: NONE, reserved: GO },
  /** Движение товара: приход, расход */
  movement: { in: OK, out: NONE },
  /** Срок действия цены поставщика */
  validity: { ok: OK, expiring: W, expired: NO },
  /** Запрос на новую категорию каталога */
  categoryRequest: { pending: W, approved: OK, rejected: NO },
  /** Вид позиции каталога и строки расчёта — категория, не статус: товар, под заказ, услуга */
  itemKind: {
    goods: GO,
    stock: GO,
    goods_to_order: MEMO,
    on_order: MEMO,
    service: EXT,
    service_fixed: EXT,
    service_milestones: EXT,
    service_time: EXT,
  },
  /** Происхождение записи: курс ЦБ / вручную, образец / свой шаблон */
  origin: { auto: GO, CBU: GO, sample: GO, manual: W, MANUAL: W, own: NONE },
  /** Запись справочника включена или выключена */
  activity: { active: OK, inactive: OFF },
  /** Доступ сотрудника к системе и привязка Telegram */
  access: { yes: OK, no: NONE, pending: W, error: NO },
  /** Сотрудник */
  employee: { active: OK, invited: W, disabled: OFF },
  /** Обращение к администратору: новое и в работе — синие, решено — зелёное */
  ticket: { new: GO, in_progress: GO, resolved: OK },
  /** Шаг первого запуска */
  setupStep: { done: OK, todo: W, unknown: NONE },
  /** Статья компании */
  article: { draft: DR, published: OK },
  /** Уровень здоровья интеграции и важность пункта «Требует внимания» */
  integration: { ok: OK, warn: W, fail: NO, unknown: NONE, off: OFF, info: NONE },
  /** Состояние сервиса (интеграции, «О системе») */
  service: {
    ok: OK,
    broken: NO,
    fail: NO,
    unstable: W,
    degraded: W,
    not_configured: OFF,
    disabled: OFF,
    expected: OFF,
    not_checked: NONE,
  },
  /** Модель ИИ */
  modelHealth: { ok: OK, problem: NO, unknown: NONE },
  /** Письмо в журнале почты */
  mail: { queued: NONE, sent: GO, failed: NO, skipped_no_smtp: OFF },
  /** Подписчик шины */
  busSubscriber: {
    ok: OK,
    failing: W,
    paused: NO,
    dead_letters: NO,
    disabled: OFF,
    removed: OFF,
  },
  /** Доставка события шины */
  busDelivery: { pending: W, retrying: W, in_flight: GO, delivered: OK, dead: NO },
  /** Входящее событие шины */
  busInbox: { received: OK, retrying: W, processed: OK, failed: NO, skipped: OFF },
  /** Документ базы знаний: разбор */
  kbIngest: { pending: W, processing: GO, done: OK, failed: NO },
  /** Пробел базы знаний */
  kbGap: { open: W, resolved: OK, ignored: OFF },
  /** Важность передачи диалога менеджеру */
  handoffPriority: { hot: NO, warm: W, info: NONE },
  /** Бейдж срока в «Моих задачах» (SPEC-v3 §7.1): сегодня и просрочено — красный, завтра — золотой, служебка — фиолетовый */
  due: { overdue: NO, today: NO, tomorrow: W, memo: MEMO, later: NONE },
  /** Значок вкладки уведомления: решения, клиенты (внешний канал), система */
  notification: { all: GO, decisions: W, clients: EXT, system: NO },
  /** Пункт чек-листа одобрения КП */
  check: { ok: OK, fail: NO, pending: W },
} as const satisfies Record<string, Record<string, StatusTone>>;

export type StatusKind = keyof typeof STATUS_TONE;
export type StatusCode<K extends StatusKind> = keyof (typeof STATUS_TONE)[K] & string;

export const STATUS_KINDS = Object.keys(STATUS_TONE) as StatusKind[];

/**
 * Коды со словом в словаре `dictionary:status.<вид>.<код>` (SPEC-v3 §2.4) и стадии `dictionary:stage.<код>`; у остальных
 * кодов слово даёт модуль (`children` у `StatusTag`).
 */
export const DICTIONARY_STATUS = {
  incoming: ["registered", "awaiting_resolution", "resolved", "returned", "rejected"],
  quote: ["draft", "revision", "approved", "sent", "accepted", "declined", "expired"],
  contract: ["draft", "agreed", "issued", "signed", "rejected"],
  invoice: ["issued", "proof_received", "partially_paid", "paid", "overdue"],
  act: ["draft", "issued", "signed", "returned"],
  memo: ["pending", "approved", "rejected", "returned", "passed_to_accountant", "paid"],
  lead: ["new", "dialog", "wants_quote", "no_answer", "client", "lost"],
  stage: [...STAGES, "LOST"],
} as const satisfies Partial<Record<StatusKind, readonly string[]>>;

/** Цвет статуса; неизвестный код (бэкенд опередил фронт) — нейтральный, слово покажет сам код. */
export function statusTone(kind: StatusKind, status: string): StatusTone {
  const map: Record<string, StatusTone> = STATUS_TONE[kind];
  return map[status] ?? "default";
}

/** Цвет и фон значка (не тега) по статусу: чип уведомления, значок чек-листа. */
export function statusStyle(kind: StatusKind, status: string): ToneStyle {
  return TONE_STYLE[statusTone(kind, status)];
}

/** У кода есть слово в словаре (`DICTIONARY_STATUS`). */
export function isKnownStatus(kind: StatusKind, status: string): boolean {
  const words: Partial<Record<StatusKind, readonly string[]>> = DICTIONARY_STATUS;
  return words[kind]?.includes(status) ?? false;
}

/** Цвет аватара по имени — один человек всегда одного цвета (декоративный, имя рядом словами). */
const AVATAR_TONES: readonly StatusTone[] = ["blue", "gold", "cyan", "purple"];
export function avatarStyle(name: string): ToneStyle {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + (char.codePointAt(0) ?? 0)) % 997;
  return TONE_STYLE[AVATAR_TONES[hash % AVATAR_TONES.length] ?? "blue"];
}

/** Ключ слова статуса в i18n: `dictionary:status.invoice.paid`, для стадий — `dictionary:stage.QUOTE`. */
export function statusLabelKey(kind: StatusKind, status: string): string {
  return kind === "stage" ? `dictionary:stage.${status}` : `dictionary:status.${kind}.${status}`;
}
