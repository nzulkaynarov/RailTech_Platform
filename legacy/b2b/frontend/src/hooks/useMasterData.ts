import { useQuery } from '@tanstack/react-query';
import { masterDataApi } from '../api/masterDataApi';

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
