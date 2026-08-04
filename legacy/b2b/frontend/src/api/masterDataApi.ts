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
  alpha3: string;
  /** Цифровой код ISO 3166-1 («860», «643») — язык таможенных систем. */
  iso_numeric: string;
  /** Выверенная ставка НДС; `null` = неизвестна (для большинства стран мира). */
  vat_rate: string | null;
}

export interface Currency extends LookupItem {
  symbol: string;
}

export type MasterKind = 'countries' | 'currencies' | 'units' | 'delivery-basis';

export const masterDataApi = {
  getCountries: () => apiClient.get<Country[]>('master-data/countries/').then(r => r.data),
  getCurrencies: () => apiClient.get<Currency[]>('master-data/currencies/').then(r => r.data),
  getUnits: () => apiClient.get<LookupItem[]>('master-data/units/').then(r => r.data),
  getDeliveryBases: () => apiClient.get<LookupItem[]>('master-data/delivery-basis/').then(r => r.data),
  create: async <T extends Record<string, unknown>>(kind: MasterKind, data: T) => {
    const response = await apiClient.post(`master-data/${kind}/`, data);
    return response.data;
  },
  update: async <T extends Record<string, unknown>>(kind: MasterKind, id: number, data: T) => {
    const response = await apiClient.patch(`master-data/${kind}/${id}/`, data);
    return response.data;
  },
  remove: async (kind: MasterKind, id: number) => {
    await apiClient.delete(`master-data/${kind}/${id}/`);
  },
  /** Платежи по коду ТН ВЭД и стране происхождения (витрина ГТК, суточный кэш на бэкенде). */
  getCustomsDuties: (hsCode: string, originCode: string) =>
    apiClient
      .get<CustomsDuties>(`master-data/hs-codes/${hsCode}/duties/`, { params: { origin: originCode } })
      .then((r) => r.data),
};

/** Строка платежа из интегрированного тарифа ГТК. `rate` пуст, когда ставки в тарифе нет —
 *  интерфейс рисует «—» и НЕ подставляет «0%» (это додумывание за таможню). */
export interface CustomsPayment {
  /** Цифровой код платежа ГТК: 10 сбор, 20 пошлина, 27 акциз, 29 НДС. Пусто — строка без кода. */
  code: string;
  /** Подпись источника (узбекская) — показываем только для строк без известного кода. */
  source_label: string;
  rate: string;
  legal_basis: string;
}

export interface CustomsPermit {
  organization: string;
  document: string;
  legal_basis: string;
  document_kind: string;
}

export interface CustomsDuties {
  hs_code: string;
  hs_name: string;
  origin: string;
  payments: CustomsPayment[];
  permits: CustomsPermit[];
  fetched_at: string;
  source_url: string;
}
