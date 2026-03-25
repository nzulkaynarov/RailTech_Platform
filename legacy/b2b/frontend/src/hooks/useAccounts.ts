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
