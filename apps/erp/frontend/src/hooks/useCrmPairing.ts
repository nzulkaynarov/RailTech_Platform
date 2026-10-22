import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { crmPairingApi } from '@/api/crmPairingApi';

export const CRM_PAIRING_KEY = ['crmPairing'] as const;

/** Статус сопряжения с CRM (только администратор). Без опроса: обновляется кнопкой и при возврате в окно. */
export const useCrmPairingStatus = () => useQuery({
  queryKey: CRM_PAIRING_KEY,
  queryFn: () => crmPairingApi.getStatus(),
});

/** Выпуск одноразового кода; прежний неиспользованный гасится на сервере. Код нигде не кэшируется. */
export const useIssuePairingCode = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => crmPairingApi.issueCode(),
    gcTime: 0,
    onSuccess: () => { qc.invalidateQueries({ queryKey: CRM_PAIRING_KEY }); },
  });
};
