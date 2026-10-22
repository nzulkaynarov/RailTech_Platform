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
 * Карты «статус → цвет» для тегов (SPEC-v3 §2.4 для документов; лид — 04-integration-map §3.1; стадия — §2.3). Ключ —
 * код статуса; слово берётся из словаря `dictionary:status.<вид>.<код>`. Коды BFF для документов в контракте пока не
 * заданы (QUESTIONS Q-PLT-13-1): карта — рабочее соглашение Платформы, при расхождении правится она.
 */
export const STATUS_TONE = {
  /** Входящее письмо */
  incoming: {
    registered: "blue",
    awaiting_resolution: "gold",
    resolved: "green",
    returned: "gold",
    rejected: "red",
  },
  /** КП */
  quote: {
    draft: "gold",
    revision: "gold",
    approved: "blue",
    sent: "blue",
    accepted: "green",
    declined: "red",
    expired: "default",
  },
  /** Договор */
  contract: {
    draft: "default",
    agreed: "blue",
    issued: "gold",
    signed: "green",
    rejected: "red",
  },
  /** Счёт */
  invoice: {
    issued: "blue",
    proof_received: "gold",
    partially_paid: "gold",
    paid: "green",
    overdue: "red",
  },
  /** Акт */
  act: {
    draft: "default",
    issued: "blue",
    signed: "green",
    returned: "gold",
  },
  /** Служебная записка */
  memo: {
    pending: "gold",
    approved: "green",
    rejected: "red",
    returned: "gold",
    passed_to_accountant: "blue",
    paid: "green",
  },
  /** Лид (`platform_status`, CRM-02) */
  lead: {
    new: "blue",
    dialog: "cyan",
    wants_quote: "gold",
    no_answer: "red",
    client: "green",
    lost: "default",
  },
  /** Стадия заявки/проекта */
  stage: {
    REQUEST: "blue",
    RESOLUTION: "blue",
    CALCULATION: "blue",
    QUOTE: "blue",
    CONTRACT: "blue",
    PAYMENT: "blue",
    DONE: "green",
    LOST: "red",
  },
} as const satisfies Record<string, Record<string, StatusTone>>;

export type StatusKind = keyof typeof STATUS_TONE;

export const STATUS_KINDS = Object.keys(STATUS_TONE) as StatusKind[];

/** Цвет статуса; неизвестный код (бэкенд опередил фронт) — нейтральный, слово покажет сам код. */
export function statusTone(kind: StatusKind, status: string): StatusTone {
  const map: Record<string, StatusTone> = STATUS_TONE[kind];
  return map[status] ?? "default";
}

export function isKnownStatus(kind: StatusKind, status: string): boolean {
  return status in STATUS_TONE[kind];
}

/** Ключ слова статуса в i18n: `dictionary:status.invoice.paid`, для стадий — `dictionary:stage.QUOTE`. */
export function statusLabelKey(kind: StatusKind, status: string): string {
  return kind === "stage" ? `dictionary:stage.${status}` : `dictionary:status.${kind}.${status}`;
}
