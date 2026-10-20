/**
 * Запросы и мутации CRM поверх сгенерированных хуков orval (ADR-0021).
 * Ключи кэша — сгенерированные (`get…QueryKey`); группы для инвалидации — `queryKeys`.
 */
import { keepPreviousData, useMutation, useQueryClient } from "@tanstack/react-query";

import { compact } from "./http";
import {
  assign,
  closeLost,
  closeWon,
  getListUsersQueryKey,
  getMeQueryKey,
  getPermissionsQueryKey,
  acknowledge,
  newDeal,
  note,
  reply,
  returnToBot,
  snooze,
  take,
  unsnooze,
  useGetLead,
  useInbox as useInboxQuery,
  useLeadDecisions,
  useLeadMessages,
  useLeadNotes,
  useListLeads,
  useListServiceRequests,
  useListUsers,
  useMe as useMeQuery,
  usePermissions,
  useTeam as useTeamQuery,
} from "./generated/crm";
import type { ListLeadsParams } from "./generated/model";
import { invalidateKeys, queryKeys } from "./queryKeys";

/** Сгенерированные ключи, которые страницы и провайдеры читают/кладут в кэш сами. */
export const keys = {
  me: getMeQueryKey(),
  permissions: getPermissionsQueryKey(),
  users: getListUsersQueryKey(),
};

export const useMe = () => useMeQuery();

export const usePermissionsQuery = () => usePermissions();

export const useInbox = () => useInboxQuery();

/** Открытые запросы клиентов (Q-017): самый старый первым, как в API. */
export const useOpenServiceRequests = (enabled = true) =>
  useListServiceRequests({ status: "open" }, { query: { enabled } });

/** Таблица не пустеет при смене страницы/фильтра: прошлая страница видна до ответа. */
export const useLeads = (params: ListLeadsParams) =>
  useListLeads(compact(params), { query: { placeholderData: keepPreviousData } });

/** Пока клиент лида «передаётся в бэк-офис» (FIX-31, FIX-34b) — перечитываем, как в карточке клиента. */
export const useLead = (id: number) =>
  useGetLead(id, {
    query: {
      refetchInterval: (query) =>
        query.state.data?.client_handoff_status === "pending" ? 4000 : false,
    },
  });

export const useMessages = (id: number) => useLeadMessages(id);

export const useNotes = (id: number) => useLeadNotes(id);

export const useDecisions = (id: number) => useLeadDecisions(id);

export const useUsers = () => useListUsers();

/** Активные менеджеры и админы — кому передать лида (без email и ролей). */
export const useTeam = () => useTeamQuery({ query: { staleTime: 60_000 } });

export type LeadAction =
  | { kind: "take" }
  | { kind: "acknowledge" }
  | { kind: "newDeal" }
  | { kind: "assign"; userId: number }
  | { kind: "return"; note: string | null }
  | { kind: "snooze"; until: string }
  | { kind: "unsnooze" }
  | { kind: "won"; reason: string | null; amount: number | null }
  | { kind: "lost"; reason: string | null; lostReason: string | null }
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
    case "unsnooze":
      await unsnooze(id);
      return;
    case "won":
      await closeWon(id, { reason: action.reason, amount: action.amount });
      return;
    case "lost":
      await closeLost(id, { reason: action.reason, lost_reason: action.lostReason });
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
    onSettled: () => invalidateKeys(client, [...queryKeys.lead(id), ...queryKeys.leadLists()]),
  });
}
