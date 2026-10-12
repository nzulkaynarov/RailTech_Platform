/**
 * Запросы и мутации CRM поверх сгенерированного клиента orval (react-query).
 * Ключи запросов централизованы: SSE-события инвалидируют их точечно.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { compact, unwrap } from "./http";
import {
  assign,
  closeLost,
  closeWon,
  getLead,
  inbox,
  leadDecisions,
  leadMessages,
  leadNotes,
  listLeads,
  listServiceRequests,
  listUsers,
  me,
  acknowledge,
  newDeal,
  note,
  permissions,
  reply,
  returnToBot,
  snooze,
  take,
  team,
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
  team: ["team"] as const,
  serviceRequests: ["service-requests", "open"] as const,
};

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: async () => unwrap(await me()) });

export const usePermissionsQuery = () =>
  useQuery({ queryKey: keys.permissions, queryFn: async () => unwrap(await permissions()) });

export const useInbox = () =>
  useQuery({ queryKey: keys.inbox, queryFn: async () => unwrap(await inbox()) });

/** Открытые запросы клиентов (Q-017): самый старый первым, как в API. */
export const useOpenServiceRequests = () =>
  useQuery({
    queryKey: keys.serviceRequests,
    queryFn: async () => unwrap(await listServiceRequests({ status: "open" })),
  });

export const useLeads = (params: ListLeadsParams) =>
  useQuery({
    queryKey: keys.leads(params),
    queryFn: async () => unwrap(await listLeads(compact(params))),
  });

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

/** Активные менеджеры и админы — кому передать лида (без email и ролей). */
export const useTeam = () =>
  useQuery({ queryKey: keys.team, queryFn: async () => unwrap(await team()), staleTime: 60_000 });

export type LeadAction =
  | { kind: "take" }
  | { kind: "acknowledge" }
  | { kind: "newDeal" }
  | { kind: "assign"; userId: number }
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
    case "acknowledge":
      await acknowledge(id);
      return;
    case "newDeal":
      await newDeal(id);
      return;
    case "assign":
      await assign(id, { user_id: action.userId });
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
        client.invalidateQueries({ queryKey: keys.serviceRequests }),
        client.invalidateQueries({ queryKey: ["leads"] }),
      ]),
  });
}
