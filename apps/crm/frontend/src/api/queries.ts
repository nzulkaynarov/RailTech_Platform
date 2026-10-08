/**
 * Запросы и мутации CRM поверх сгенерированного клиента orval (react-query).
 * Ключи запросов централизованы: SSE-события инвалидируют их точечно.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { unwrap } from "./http";
import {
  closeLost,
  closeWon,
  getLead,
  inbox,
  leadDecisions,
  leadMessages,
  leadNotes,
  listLeads,
  listUsers,
  me,
  note,
  permissions,
  reply,
  returnToBot,
  snooze,
  take,
} from "./generated/crm";
import type { ListLeadsParams } from "./generated/model";

export const keys = {
  me: ["me"] as const,
  permissions: ["permissions"] as const,
  inbox: ["inbox"] as const,
  leads: (params: ListLeadsParams) => ["leads", params] as const,
  lead: (id: number) => ["lead", id] as const,
  messages: (id: number) => ["lead", id, "messages"] as const,
  notes: (id: number) => ["lead", id, "notes"] as const,
  decisions: (id: number) => ["lead", id, "decisions"] as const,
  users: ["users"] as const,
};

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: async () => unwrap(await me()) });

export const usePermissionsQuery = () =>
  useQuery({ queryKey: keys.permissions, queryFn: async () => unwrap(await permissions()) });

export const useInbox = () =>
  useQuery({ queryKey: keys.inbox, queryFn: async () => unwrap(await inbox()) });

export const useLeads = (params: ListLeadsParams) =>
  useQuery({ queryKey: keys.leads(params), queryFn: async () => unwrap(await listLeads(params)) });

export const useLead = (id: number) =>
  useQuery({ queryKey: keys.lead(id), queryFn: async () => unwrap(await getLead(id)) });

export const useMessages = (id: number) =>
  useQuery({ queryKey: keys.messages(id), queryFn: async () => unwrap(await leadMessages(id)) });

export const useNotes = (id: number) =>
  useQuery({ queryKey: keys.notes(id), queryFn: async () => unwrap(await leadNotes(id)) });

export const useDecisions = (id: number) =>
  useQuery({ queryKey: keys.decisions(id), queryFn: async () => unwrap(await leadDecisions(id)) });

export const useUsers = () =>
  useQuery({ queryKey: keys.users, queryFn: async () => unwrap(await listUsers()) });

export type LeadAction =
  | { kind: "take" }
  | { kind: "return"; note: string | null }
  | { kind: "snooze"; until: string }
  | { kind: "won"; reason: string | null }
  | { kind: "lost"; reason: string | null }
  | { kind: "note"; text: string; visibleToBot: boolean }
  | { kind: "reply"; text: string };

async function runAction(id: number, action: LeadAction): Promise<void> {
  switch (action.kind) {
    case "take":
      await take(id);
      return;
    case "return":
      await returnToBot(id, { note: action.note });
      return;
    case "snooze":
      await snooze(id, { until: action.until });
      return;
    case "won":
      await closeWon(id, { reason: action.reason });
      return;
    case "lost":
      await closeLost(id, { reason: action.reason });
      return;
    case "note":
      await note(id, { text: action.text, visible_to_bot: action.visibleToBot });
      return;
    case "reply":
      await reply(id, { text: action.text });
  }
}

/** Действие над лидом; после успеха перечитываются карточка, переписка и входящие. */
export function useLeadAction(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: LeadAction) => runAction(id, action),
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ["lead", id] }),
        client.invalidateQueries({ queryKey: keys.inbox }),
        client.invalidateQueries({ queryKey: ["leads"] }),
      ]),
  });
}
