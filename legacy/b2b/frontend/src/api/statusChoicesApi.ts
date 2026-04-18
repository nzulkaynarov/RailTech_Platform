import { apiClient } from './client';

export interface StatusChoice {
  code: string;
  label: string;
}

export interface Phase2StatusChoices {
  contract: StatusChoice[];
  invoice: StatusChoice[];
  act: StatusChoice[];
  fulfillment: StatusChoice[];
  supplier_bid: StatusChoice[];
  payment_method: StatusChoice[];
}

export const statusChoicesApi = {
  getAll: async () => {
    const response = await apiClient.get<Phase2StatusChoices>('crm/status-choices/');
    return response.data;
  },
};
