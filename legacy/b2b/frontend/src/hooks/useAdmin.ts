import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi, emailTemplatesApi, operatorRolesApi, entitlementsApi } from '@/api/adminApi';
import type { EmailTemplateDraft, OperatorRoleDraft, CompanyEntitlementDraft } from '@/api/adminApi';

export const useAdminQueue = (queueType?: string) =>
  useQuery({
    queryKey: ['admin-queue', queueType || 'all'],
    queryFn: () => adminApi.getQueue({ queue_type: queueType }),
    staleTime: 30_000,
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  });

export const useAdminPulse = (period: '7d' | '30d' | '90d' = '30d') =>
  useQuery({
    queryKey: ['admin-pulse', period],
    queryFn: () => adminApi.getPulse(period),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });

export const useAdminSearch = (q: string) =>
  useQuery({
    queryKey: ['admin-search', q],
    queryFn: () => adminApi.search(q),
    enabled: q.trim().length >= 2,
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });

/**
 * ОТКРЫТЫЙ ВОПРОС ВЛАДЕЛЬЦУ, а не забытый код (аудит UI 2026-07-30, §3.2).
 *
 * Пообъектная история для оператора: эндпоинт есть, но поверхности, где её показать, нет —
 * лента на дашборде платформенная, а не по конкретной компании/пользователю. Естественный дом
 * — карточки в операторских реестрах; делать это без решения владельца не стал, потому что это
 * новый блок интерфейса, а не проводка существующего.
 */
export const useAdminActivity = (entityType: string, entityId: number | string | undefined) =>
  useQuery({
    queryKey: ['admin-activity', entityType, entityId],
    queryFn: () => adminApi.getActivity(entityType, entityId as number),
    enabled: Boolean(entityType) && entityId !== undefined && entityId !== null && entityId !== '',
    staleTime: 15_000,
  });

export const useAccessLog = (limit = 100) =>
  useQuery({
    queryKey: ['admin-access-log', limit],
    queryFn: () => adminApi.getAccessLog(limit),
    staleTime: 15_000,
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  });

export const useBulkVerifyKYC = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, level, reason }: { ids: number[]; level?: string; reason?: string }) =>
      adminApi.bulkVerifyKYC(ids, level, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['companies'] });
      queryClient.invalidateQueries({ queryKey: ['admin-queue'] });
      queryClient.invalidateQueries({ queryKey: ['platform-dashboard'] });
    },
  });
};

/* ─── Email templates ───────────────────────────────────────────────── */

const EMAIL_TEMPLATES_KEY = ['admin-email-templates'];

export const useEmailTemplates = () =>
  useQuery({
    queryKey: EMAIL_TEMPLATES_KEY,
    queryFn: () => emailTemplatesApi.list(),
    staleTime: 30_000,
  });

export const useCreateEmailTemplate = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: EmailTemplateDraft) => emailTemplatesApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EMAIL_TEMPLATES_KEY });
    },
  });
};

export const useUpdateEmailTemplate = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<EmailTemplateDraft> }) =>
      emailTemplatesApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EMAIL_TEMPLATES_KEY });
    },
  });
};

export const useDeleteEmailTemplate = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => emailTemplatesApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EMAIL_TEMPLATES_KEY });
    },
  });
};

export const usePreviewEmailTemplate = () =>
  useMutation({
    mutationFn: ({ id, context }: { id: number; context?: Record<string, unknown> }) =>
      emailTemplatesApi.preview(id, context),
  });

export const useTestSendEmailTemplate = () =>
  useMutation({
    mutationFn: ({
      id,
      toEmail,
      context,
    }: {
      id: number;
      toEmail: string;
      context?: Record<string, unknown>;
    }) => emailTemplatesApi.testSend(id, toEmail, context),
  });

/* ─── Operator roles (ADR-0004 G1) ──────────────────────────────────── */

const OPERATOR_ROLES_KEY = ['admin-operator-roles'];

export const useOperatorRoles = () =>
  useQuery({
    queryKey: OPERATOR_ROLES_KEY,
    queryFn: () => operatorRolesApi.list(),
    staleTime: 30_000,
  });

export const useOperatorPermissionCatalog = () =>
  useQuery({
    queryKey: ['admin-operator-permissions'],
    queryFn: () => operatorRolesApi.permissionCatalog(),
    staleTime: 5 * 60_000,
  });

export const useCreateOperatorRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: OperatorRoleDraft) => operatorRolesApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: OPERATOR_ROLES_KEY });
    },
  });
};

export const useUpdateOperatorRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: OperatorRoleDraft }) =>
      operatorRolesApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: OPERATOR_ROLES_KEY });
    },
  });
};

export const useDeleteOperatorRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => operatorRolesApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: OPERATOR_ROLES_KEY });
    },
  });
};

export const useAssignOperatorRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, roleId }: { userId: number; roleId: number | null }) =>
      operatorRolesApi.assign(userId, roleId),
    onSuccess: () => {
      // The assigned role's operator_count + the user's operator_role both change.
      queryClient.invalidateQueries({ queryKey: OPERATOR_ROLES_KEY });
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
};

export const useBulkSubscriptionStatus = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      ids,
      status,
      reason,
    }: {
      ids: number[];
      status: 'ACTIVE' | 'SUSPENDED';
      reason?: string;
    }) => adminApi.bulkSetSubscriptionStatus(ids, status, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
      queryClient.invalidateQueries({ queryKey: ['admin-queue'] });
      queryClient.invalidateQueries({ queryKey: ['platform-dashboard'] });
    },
  });
};

/* ─── Company entitlements — Move 4 monetization control plane (ADR-0006) ─── */

const ENTITLEMENTS_KEY = ['admin-entitlements'];

export const useEntitlements = (params?: { company?: number; feature_key?: string; access?: string; search?: string }) =>
  useQuery({
    queryKey: [...ENTITLEMENTS_KEY, params ?? {}],
    queryFn: () => entitlementsApi.list(params),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });

export const useEntitlementChoices = () =>
  useQuery({
    queryKey: ['admin-entitlement-choices'],
    queryFn: () => entitlementsApi.choices(),
    staleTime: 5 * 60_000,
  });

export const useCreateEntitlement = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CompanyEntitlementDraft) => entitlementsApi.create(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ENTITLEMENTS_KEY }),
  });
};

export const useUpdateEntitlement = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<CompanyEntitlementDraft> }) =>
      entitlementsApi.update(id, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ENTITLEMENTS_KEY }),
  });
};

export const useDeleteEntitlement = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => entitlementsApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ENTITLEMENTS_KEY }),
  });
};
