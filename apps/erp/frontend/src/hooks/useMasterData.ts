import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { masterDataApi, MasterKind } from '../api/masterDataApi';

// `includeInactive` входит в ключ запроса: выборка с отключёнными строками — ДРУГИЕ данные,
// и склеивать её с общим списком, на котором висят выпадающие списки всех экранов, нельзя.
export const useCurrencies = (includeInactive = false) => useQuery({
  queryKey: ['master-data', 'currencies', includeInactive],
  queryFn: () => masterDataApi.getCurrencies(includeInactive),
  staleTime: 5 * 60_000,
});

export const useUnits = (includeInactive = false) => useQuery({
  queryKey: ['master-data', 'units', includeInactive],
  queryFn: () => masterDataApi.getUnits(includeInactive),
  staleTime: 5 * 60_000,
});

export const useCountries = (includeInactive = false) => useQuery({
  queryKey: ['master-data', 'countries', includeInactive],
  queryFn: () => masterDataApi.getCountries(includeInactive),
  staleTime: 5 * 60_000,
});

export const useDeliveryBases = (includeInactive = false) => useQuery({
  queryKey: ['master-data', 'delivery-bases', includeInactive],
  queryFn: () => masterDataApi.getDeliveryBases(includeInactive),
  staleTime: 5 * 60_000,
});

// Префикс БЕЗ признака выборки: правка обязана сбрасывать и обычный список, и список с
// отключёнными строками (react-query сверяет ключи по префиксу).
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
