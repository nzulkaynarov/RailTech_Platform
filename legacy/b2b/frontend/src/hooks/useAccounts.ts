import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { accountsApi, User, UserFilterParams, CompanyFilterParams } from '../api/accountsApi';

export const useUsers = (params?: UserFilterParams) => useQuery({
  queryKey: ['users', params],
  queryFn: () => accountsApi.getUsers(params),
});

export const useCreateUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<User>) => accountsApi.createUser(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
};

export const useUpdateUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number, data: Partial<User> }) => 
      accountsApi.updateUser(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
};

export const useDeleteUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => accountsApi.deleteUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
};

export const useSystemRoles = () => useQuery({
  queryKey: ['system-roles'],
  queryFn: () => accountsApi.getSystemRoles(),
  staleTime: 30 * 60_000,
});

export const useWorkspaceRoles = (companyType?: string) => useQuery({
  queryKey: ['workspace-roles', companyType ?? 'all'],
  queryFn: () => accountsApi.getWorkspaceRoles(companyType),
  staleTime: 30 * 60_000,
});

export const useChangeUserRole = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, role }: { id: number; role: string }) => accountsApi.updateUserRole(id, role),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
};

export const useAddUserMembership = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      params: { userId: number; company: number; workspaceRole: string; isPrimary?: boolean },
    ) =>
      accountsApi.addUserMembership(params.userId, {
        company: params.company,
        workspace_role: params.workspaceRole,
        is_primary: params.isPrimary ?? false,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
};

export const useRemoveUserMembership = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, membershipId }: { userId: number; membershipId: number }) =>
      accountsApi.removeUserMembership(userId, membershipId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
};

export const useToggleUserActive = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => accountsApi.toggleUserActiveStatus(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
};

export const useCompanies = (params?: CompanyFilterParams) => useQuery({
  queryKey: ['companies', params],
  queryFn: () => accountsApi.getCompanies(params),
});

export const useCreateCompany = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof accountsApi.createCompany>[0]) => accountsApi.createCompany(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['companies'] }),
  });
};

export const useUpdateCompany = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof accountsApi.updateCompany>[1] }) =>
      accountsApi.updateCompany(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['companies'] }),
  });
};

export const useDeleteCompany = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => accountsApi.deleteCompany(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['companies'] }),
  });
};

export const useCompanyTeam = (companyId: number | null) => useQuery({
  queryKey: ['company-team', companyId],
  queryFn: () => accountsApi.getTeam(companyId as number),
  enabled: !!companyId,
  staleTime: 60_000,
});

export const useInviteMember = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ companyId, email, role }: { companyId: number; email: string; role: string }) =>
      accountsApi.inviteUser(companyId, { email, role }),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['company-team', variables.companyId] });
      qc.invalidateQueries({ queryKey: ['users'] });
    },
  });
};

export const useVerifyCompany = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, statusCode, comment }: { id: number; statusCode: string; comment?: string }) =>
      accountsApi.verifyCompany(id, statusCode, comment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['companies'] });
    },
  });
};

export const useUploadDocument = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ companyId, file, docType }: { companyId: number; file: File; docType: string }) =>
      accountsApi.uploadDocument(companyId, file, docType),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['companies'] });
    },
  });
};

// ─── Subscriptions ─────────────────────────────────────────────────────

export const useSubscriptions = () => useQuery({
  queryKey: ['subscriptions'],
  queryFn: () => accountsApi.getSubscriptions(),
});

export const useActivateSubscription = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => accountsApi.activateSubscription(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['subscriptions'] }); },
  });
};

export const useSuspendSubscription = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => accountsApi.suspendSubscription(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['subscriptions'] }); },
  });
};

export const usePaySubscription = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, amount, months }: { id: number; amount: string; months?: number }) =>
      accountsApi.paySubscription(id, amount, months ?? 1),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['subscriptions'] }),
  });
};

export const useCreateSubscription = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof accountsApi.createSubscription>[0]) => accountsApi.createSubscription(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['subscriptions'] }),
  });
};

export const useUpdateSubscription = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof accountsApi.updateSubscription>[1] }) =>
      accountsApi.updateSubscription(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['subscriptions'] }),
  });
};

export const useDeleteSubscription = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => accountsApi.deleteSubscription(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['subscriptions'] }),
  });
};

// ─── Role Applications ─────────────────────────────────────────────────

export const useRoleApplications = () => useQuery({
  queryKey: ['roleApplications'],
  queryFn: () => accountsApi.getRoleApplications(),
});

export const useApproveRoleApplication = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => accountsApi.approveRoleApplication(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['roleApplications'] }); },
  });
};

export const useRejectRoleApplication = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) =>
      accountsApi.rejectRoleApplication(id, reason),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['roleApplications'] }); },
  });
};
