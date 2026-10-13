/**
 * «Кто ведёт» лида — одно значение вместо пары «ответственный + режим бота»
 * (аудит 2026-10-12): во время передачи никогда не «Ведёт бот».
 */
import type { LeadOut } from "../api/generated/model";
import { t } from "../i18n/ru";
import { formatWait } from "./sla";

const label = (key: string): string => t.owner[key] ?? key;

export type WhoLeads =
  | { kind: "waiting"; label: string }
  | { kind: "human"; label: string }
  | { kind: "paused"; label: string }
  | { kind: "bot"; label: string };

type LeadLike = Pick<LeadOut, "owner_mode" | "assigned_user_name"> & {
  escalation?: Pick<NonNullable<LeadOut["escalation"]>, "status" | "created_at"> | null;
};

const WAITING = new Set(["open", "snoozed"]);

export function whoLeads(lead: LeadLike, now: Date = new Date()): WhoLeads {
  const e = lead.escalation;
  if (lead.owner_mode !== "human" && e && WAITING.has(e.status)) {
    const waited = formatWait(now.getTime() - new Date(e.created_at).getTime());
    return { kind: "waiting", label: label("waiting").replace("{wait}", waited) };
  }
  if (lead.owner_mode === "human") {
    return { kind: "human", label: lead.assigned_user_name ?? label("human") };
  }
  if (lead.owner_mode === "paused") return { kind: "paused", label: label("paused") };
  return { kind: "bot", label: label("bot") };
}
