import { apiClient } from './client';

export interface LookupItem {
  id: number;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
}

export interface Country extends LookupItem {
  alpha2: string;
  vat_rate: string;
}

export interface Currency extends LookupItem {
  symbol: string;
}

export const masterDataApi = {
  getCountries: () => apiClient.get<Country[]>('master-data/countries/').then(r => r.data),
  getCurrencies: () => apiClient.get<Currency[]>('master-data/currencies/').then(r => r.data),
  getUnits: () => apiClient.get<LookupItem[]>('master-data/units/').then(r => r.data),
  getDeliveryBases: () => apiClient.get<LookupItem[]>('master-data/delivery-basis/').then(r => r.data),
};
