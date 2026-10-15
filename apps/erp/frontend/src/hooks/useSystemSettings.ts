import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { systemApi, SystemSettings } from '@/api/systemApi';

export const useSystemSettings = (options?: { enabled?: boolean }) => useQuery({
  queryKey: ['systemSettings'],
  queryFn: () => systemApi.getSettings(),
  ...options,
});

export const useUpdateSystemSettings = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<SystemSettings>) => systemApi.updateSettings(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['systemSettings'] }); },
  });
};
