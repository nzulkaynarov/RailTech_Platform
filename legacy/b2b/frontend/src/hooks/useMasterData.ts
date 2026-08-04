import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { masterDataApi, MasterKind } from '../api/masterDataApi';

export const useCurrencies = () => useQuery({
  queryKey: ['master-data', 'currencies'],
  queryFn: masterDataApi.getCurrencies,
  staleTime: 5 * 60_000,
});

export const useUnits = () => useQuery({
  queryKey: ['master-data', 'units'],
  queryFn: masterDataApi.getUnits,
  staleTime: 5 * 60_000,
});

export const useCountries = () => useQuery({
  queryKey: ['master-data', 'countries'],
  queryFn: masterDataApi.getCountries,
  staleTime: 5 * 60_000,
});

export const useDeliveryBases = () => useQuery({
  queryKey: ['master-data', 'delivery-bases'],
  queryFn: masterDataApi.getDeliveryBases,
  staleTime: 5 * 60_000,
});

const keyFor = (kind: MasterKind) => {
  switch (kind) {
    case 'countries': return ['master-data', 'countries'];
    case 'currencies': return ['master-data', 'currencies'];
    case 'units': return ['master-data', 'units'];
    case 'delivery-basis': return ['master-data', 'delivery-bases'];
  }
};

export const useCreateLookup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, data }: { kind: MasterKind; data: Record<string, unknown> }) =>
      masterDataApi.create(kind, data),
    onSuccess: (_r, v) => qc.invalidateQueries({ queryKey: keyFor(v.kind) }),
  });
};

export const useUpdateLookup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, id, data }: { kind: MasterKind; id: number; data: Record<string, unknown> }) =>
      masterDataApi.update(kind, id, data),
    onSuccess: (_r, v) => qc.invalidateQueries({ queryKey: keyFor(v.kind) }),
  });
};

export const useDeleteLookup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, id }: { kind: MasterKind; id: number }) => masterDataApi.remove(kind, id),
    onSuccess: (_r, v) => qc.invalidateQueries({ queryKey: keyFor(v.kind) }),
  });
};

/** Таможенные платежи по коду ТН ВЭД. Запрос идёт только когда выбрана страна происхождения:
 *  без неё ставка бессмысленна (преференции зависят именно от страны). */
export const useCustomsDuties = (hsCode: string, originCode: string) => useQuery({
  queryKey: ['customs-duties', hsCode, originCode],
  queryFn: () => masterDataApi.getCustomsDuties(hsCode, originCode),
  enabled: Boolean(hsCode) && Boolean(originCode),
  // Бэкенд держит суточный кэш; на клиенте достаточно не дёргать повтор в рамках сессии.
  staleTime: 30 * 60_000,
  retry: false,
});
