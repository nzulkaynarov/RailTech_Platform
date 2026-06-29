import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi, emailTemplatesApi, operatorRolesApi } from '@/api/adminApi';
import type { EmailTemplateDraft, OperatorRoleDraft } from '@/api/adminApi';

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
