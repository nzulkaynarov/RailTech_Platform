import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { accountsApi, User, UserFilterParams, CompanyFilterParams } from '../api/accountsApi';
import { useUserStore } from '../store/userStore';

// ─── Company Roles & Permissions ─────────────────────────────────────────────

export const useCompanyRoles = (companyId?: number) => useQuery({
  queryKey: ['company-roles', companyId],
  queryFn: () => accountsApi.getCompanyRoles(companyId),
  staleTime: 60_000,
});

export const useCreateCompanyRole = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; permissions: string[] }) =>
      accountsApi.createCompanyRole(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['company-roles'] }),
  });
};

export const useUpdateCompanyRole = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: { name?: string; permissions?: string[] } }) =>
      accountsApi.updateCompanyRole(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['company-roles'] }),
  });
};

export const useDeleteCompanyRole = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => accountsApi.deleteCompanyRole(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['company-roles'] }),
  });
};

export const useAssignMemberRole = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { member_id: number; role_id: number }) =>
      accountsApi.assignMemberRole(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['company-team'] });
      qc.invalidateQueries({ queryKey: ['company-roles'] });
    },
  });
};

export const usePermissionCatalog = () => useQuery({
  queryKey: ['permission-catalog'],
  queryFn: () => accountsApi.getPermissionCatalog(),
  staleTime: 5 * 60_000,
});

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

export const useUpdateMemberCapabilities = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { companyId: number; member_id: number; can_sell?: boolean; can_buy?: boolean }) =>
      accountsApi.updateMemberCapabilities(params.companyId, {
        member_id: params.member_id,
        can_sell: params.can_sell,
        can_buy: params.can_buy,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['company-team'] });
      qc.invalidateQueries({ queryKey: ['companies'] });
      qc.invalidateQueries({ queryKey: ['me'] });
    },
  });
};

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

export const useCompanies = (params?: CompanyFilterParams, enabled = true) => useQuery({
  queryKey: ['companies', params],
  queryFn: () => accountsApi.getCompanies(params),
  enabled,
});

/** Verified-supplier directory for the open-RFQ invite flow (member-accessible). */
export const usePartnerSuppliers = (enabled = true) => useQuery({
  queryKey: ['partner-suppliers'],
  queryFn: () => accountsApi.getPartnerSuppliers(),
  enabled,
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

export const useArchiveCompany = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => accountsApi.archiveCompany(id, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['companies'] });
    },
  });
};

export const useUnarchiveCompany = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => accountsApi.unarchiveCompany(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['companies'] });
    },
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

// S3 (P2): remove a member from the company. Invalidates the team query so the
// row disappears; never-orphan errors surface to the caller for a toast.
export const useRemoveMember = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ companyId, memberId }: { companyId: number; memberId: number }) =>
      accountsApi.removeMember(companyId, memberId),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['company-team', variables.companyId] });
      qc.invalidateQueries({ queryKey: ['users'] });
    },
  });
};

// S3 (P8): activate / deactivate a member. Invalidates the team query so the
// real status badge refreshes.
export const useToggleMemberActive = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ companyId, memberId }: { companyId: number; memberId: number }) =>
      accountsApi.toggleMemberActive(companyId, memberId),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['company-team', variables.companyId] });
      qc.invalidateQueries({ queryKey: ['users'] });
    },
  });
};

export const useUploadCompanyLogo = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ companyId, file }: { companyId: number; file: File }) =>
      accountsApi.uploadCompanyLogo(companyId, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['companies'] }),
  });
};

export const useDeleteCompanyLogo = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (companyId: number) => accountsApi.deleteCompanyLogo(companyId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['companies'] }),
  });
};

export const useUploadUserAvatar = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, file }: { userId: number; file: File }) =>
      accountsApi.uploadUserAvatar(userId, file),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
};

export const useDeleteUserAvatar = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: number) => accountsApi.deleteUserAvatar(userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
};

// ─── Subscriptions ─────────────────────────────────────────────────────

export const useSubscriptions = (params?: {
  search?: string;
  status?: string;
  plan?: string;
  ordering?: string;
  fetchAll?: boolean;
}) => useQuery({
  queryKey: ['subscriptions', params],
  queryFn: () => accountsApi.getSubscriptions(params),
});

export const useMySubscription = () => {
  // Subscriptions are a seller concern, so idle until the store actually reads SELLER —
  // the pre-auth default is BUYER, which also closes the login race window (AppShell
  // mounts and the query would fire before loadFromAuth resolves /me).
  const activeStatus = useUserStore((s) => s.activeStatus);
  return useQuery({
    queryKey: ['my-subscription'],
    queryFn: () => accountsApi.getMySubscription(),
    staleTime: 60_000,
    enabled: activeStatus === 'SELLER',
  });
};

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
    mutationFn: ({ id, reason }: { id: number; reason: string }) => accountsApi.suspendSubscription(id, reason),
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
